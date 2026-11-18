import io
import json
from unittest.mock import Mock

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest
import tax_sale_app as app


def csv_file(rows, columns=None):
    data = pd.DataFrame(rows, columns=columns or ['Item Number', 'Tax Map Number', 'Owner Name', 'Property Address', 'Bid Amount'])
    f = io.StringIO(data.to_csv(index=False)); f.name = 'sale.csv'
    return f


def feature(parcel='001', oid=1, **props):
    return {'type': 'Feature', 'geometry': {'type': 'Polygon', 'coordinates': [[[-82,35],[-81.99,35],[-81.99,35.01],[-82,35.01],[-82,35]]]},
            'properties': {'OBJECTID':oid, 'MAPNUMBER':parcel, **props}}


def sale():
    return app.load_tax_sale_file(csv_file([[1,'001','Owner','Address',100]]))


def test_historical_dataset():
    df = app.load_tax_sale_file(None)
    assert len(df) == 642
    assert df.attrs['review_rows'].empty


@pytest.mark.parametrize('value', [None, pd.NA, float('nan'), '', ' nan ', 'NULL'])
def test_missing_parcel_ids(value):
    assert app.normalize_tax_map(value) == ''


def test_invalid_duplicate_and_leading_zero_ids():
    rows = [[1,'001','A','A','$1,250'], [2,None,'B','B',100],
            [3,'002','C','C',100], [4,'002','D','D',200],
            [5,'003','E','E',-1], [6,'004','F','F','inf']]
    df = app.load_tax_sale_file(csv_file(rows))
    assert df['Tax Map Number'].tolist() == ['001']
    assert df['Bid Amount'].tolist() == [1250]
    assert len(df.attrs['review_rows']) == 5


def test_trimmed_headings_keep_leading_zeros_and_address_alias():
    f=csv_file([[1,'001','A','A',100]],['Item Number',' Tax Map Number ','Owner Name','Address','Bid Amount'])
    df=app.load_tax_sale_file(f)
    assert df['Tax Map Number'].iloc[0] == '001'
    assert 'Property Address' in df


def test_excel_and_legacy_max_bid():
    df=pd.DataFrame([[1,'001','A','A',100,300]],columns=['Item Number','Tax Map Number','Owner Name','Property Address','Bid Amount','Max Bid'])
    f=io.BytesIO();df.to_excel(f,index=False);f.seek(0);f.name='sale.xlsx'
    result=app.load_tax_sale_file(f)
    assert result['Tax Map Number'].iloc[0]=='001'
    assert result['Max Return Bid'].iloc[0]==300


@pytest.mark.parametrize('props,expected', [
    ({},'Unknown / Review'),({'LandUse':'100'},'Unknown / Review'),
    ({'LandUse':'Vacant land'},'Land / Other'),
    ({'PropertyType':'RES'},'Residential'),
    ({'LandUse':'Retail store'},'Commercial'),
    ({'LandUse':'Warehouse'},'Industrial'),
    ({'LandUse':'Office and residential'},'Unknown / Review'),
    ({'LandUse':'Plantation'},'Unknown / Review'),
])
def test_classification(props,expected):
    assert app.classify_property_use(props)==expected


def test_multiple_geometries_preserved_and_missing_geometry_reported():
    f1=feature();f2=feature(oid=2)
    g,u=app.merge_tax_data({'features':[f1,f2]},sale())
    assert len(g['features'])==2 and app.parcel_count(g)==1 and not u
    f1['geometry']=None
    g,u=app.merge_tax_data({'features':[f1]},sale())
    assert not g['features'] and u==['001']


def test_filters_literal_search_and_quick_classes():
    g,_=app.merge_tax_data({'features':[feature(PropertyType='RES')]},sale())
    args=dict(min_bid=0,max_bid=1000,selected_categories=[x[0] for x in app.BID_CATEGORIES])
    assert not app.filter_geojson(g,search_text='[',**args)['features']
    assert len(app.filter_geojson(g,search_text='owner',property_classes=['Residential'],**args)['features'])==1
    assert not app.filter_geojson(g,search_text='',property_classes=['Commercial'],**args)['features']


def setup_county(monkeypatch,responses):
    session=Mock()
    session.__enter__=Mock(return_value=session);session.__exit__=Mock(return_value=False)
    session.post.side_effect=[Mock(json=Mock(return_value=r),raise_for_status=Mock()) for r in responses]
    monkeypatch.setattr(app,'get_session',lambda:session)
    app.fetch_parcels.clear()
    return session


def test_county_keeps_distinct_object_ids_same_parcel(monkeypatch):
    setup_county(monkeypatch,[{'objectIds':[1,2],'objectIdFieldName':'OBJECTID'}, {'features':[feature(),feature(oid=2)]}])
    assert len(app.fetch_parcels(('001',))['features'])==2


@pytest.mark.parametrize('result',[{'features':[]},{'features':[feature()],'exceededTransferLimit':True},{}])
def test_incomplete_county_response_fails(monkeypatch,result):
    setup_county(monkeypatch,[{'objectIds':[1],'objectIdFieldName':'OBJECTID'},result])
    with pytest.raises(RuntimeError):app.fetch_parcels(('001',))


def test_county_batches_more_than_fifty_ids(monkeypatch):
    ids=list(range(1,52))
    session=setup_county(monkeypatch,[{'objectIds':ids,'objectIdFieldName':'OBJECTID'},
        {'features':[feature(oid=i) for i in ids[:50]]},{'features':[feature(oid=51)]}])
    assert len(app.fetch_parcels(('001',))['features'])==51
    assert session.post.call_count==3


def test_map_uses_one_geojson_layer_and_preserves_popups():
    g,_=app.merge_tax_data({'features':[feature(PropertyType='RES')]},sale())
    g['features'][0]['properties']['SaleOwnerName']='<script>alert(1)</script>'
    out=app.build_map(g).get_root().render()
    assert out.count('L.geoJson(')==1
    assert 'TAX SALE' in out and 'PROPERTY' in out and 'COUNTY VALUES' in out
    assert '<script>alert(1)</script>' not in out
    assert 'Bid amount bubbles' in out and 'Satellite' in out


def launch():
    import tax_sale_app
    tax_sale_app.main()


def test_streamlit_single_bid_and_quick_toggle(monkeypatch):
    monkeypatch.setattr(app,'load_tax_sale_file',lambda _:sale_df.copy())
    monkeypatch.setattr(app,'fetch_parcels',lambda _: {'features':[feature(PropertyType='RES')],'fetched_at':'2026-11-17T00:00:00Z'})
    test=AppTest.from_function(launch).run(timeout=20)
    assert not test.exception
    assert any('2024' in w.value for w in test.warning)
    test.radio[0].set_value('Commercial').run()
    assert not test.exception
    assert any('No parcels match' in w.value for w in test.warning)


def test_streamlit_empty_sale_stops_before_network(monkeypatch):
    empty=sale_df.iloc[:0].copy()
    monkeypatch.setattr(app,'load_tax_sale_file',lambda _:empty)
    def fail(_):raise AssertionError('County should not be queried')
    monkeypatch.setattr(app,'fetch_parcels',fail)
    test=AppTest.from_function(launch).run(timeout=20)
    assert not test.exception
    assert any('No usable' in i.value for i in test.info)


sale_df=sale()


def test_partial_appraisal_is_not_reported_as_total():
    g,_=app.merge_tax_data({'features':[feature(CurrentAppraisedLandValue=5000)]},sale())
    assert g['features'][0]['properties']['AppraisedTotal'] is None
    g,_=app.merge_tax_data({'features':[feature(CurrentAppraisedLandValue=5000,CurrentAppraisedBuildingValue=0)]},sale())
    assert g['features'][0]['properties']['AppraisedTotal']==5000
