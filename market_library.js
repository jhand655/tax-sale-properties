export default function ({parentElement, data, setStateValue}) {
  const key = "spartanburg.tax-sale.active.v1";
  const root = parentElement.querySelector("section");
  root.replaceChildren();
  root.classList.remove("update");
  function add(tag, message, parent = root) {
    const node = document.createElement(tag);
    node.textContent = message;
    parent.append(node);
    return node;
  }
  function report(active, replaced = false) {
    const value = JSON.stringify({active, replaced});
    if (root.dataset.sent !== value) {
      root.dataset.sent = value;
      setStateValue("selection", {active, replaced});
    }
  }
  let raw, active;
  try {
    raw = localStorage.getItem(key);
    active = raw ? JSON.parse(raw) : null;
    if (active && !Array.isArray(active.rows)) throw Error();
  } catch {
    add("p", "This browser could not read your saved market. Check site storage to use the library.");
    return;
  }
  if (!root.dataset.sent) report(active);
  const current = data.manual || active || data.baseline;
  add("h3", "Spartanburg County, South Carolina");
  add("p", "Active list · " + (current.name || current.year) + " · " + current.rows.length.toLocaleString() + " parcels");
  const next = data.candidate;
  if (!next) return;
  const index = rows => new Map(rows.map(r => [r["Tax Map Number"], r]));
  const oldRows = index(current.rows), newRows = index(next.rows);
  const diffs = [];
  const fields = ["Item Number", "Owner Name", "New Owner Name", "Property Address", "Bid Amount"];
  function comparable(row, key) {
    const value = String(row[key] ?? "").trim();
    return key === "Bid Amount" && value !== "" ? Number(value) : value;
  }
  for (const [id, row] of newRows) {
    const before = oldRows.get(id);
    if (!before) diffs.push(["Added", id, row["Property Address"]]);
    else {
      const changed = fields.filter(k => comparable(before, k) !== comparable(row, k));
      if (changed.length) diffs.push(["Changed", id, changed.map(k => k + ": " + (before[k] || "—") + " → " + (row[k] || "—")).join(" · ")]);
    }
  }
  for (const [id, row] of oldRows) if (!newRows.has(id)) diffs.push(["Removed", id, row["Property Address"]]);
  if (!diffs.length && current.year === next.year) {
    add("p", "Up to date with the county list."); return;
  }
  root.classList.add("update");
  add("strong", "Updated list available · " + next.year);
  add("p", ["Added","Removed","Changed"].map(type => diffs.filter(d => d[0] === type).length + " " + type.toLowerCase()).join(" · "));
  if (next.rows.some(r => !r["Bid Amount"])) add("p", "Opening bids are unpublished for some or all parcels.");
  const details = add("details", "");
  add("summary", "Review parcel changes", details);
  const scroll = add("div", "", details);
  scroll.className = "scroll";
  const table = add("table", "", scroll);
  for (const [i, cells] of [["Change","Parcel","Details"], ...diffs].entries()) {
    const tr = add("tr", "", table);
    for (const v of cells) add(i === 0 ? "th" : "td", v, tr);
  }
  const button = add("button", "Replace current list with " + next.year + " county list");
  button.onclick = () => {
    try {
      if (localStorage.getItem(key) !== raw) {
        add("p", "Your active list changed in another tab. Reload before replacing."); return;
      }
      localStorage.setItem(key, JSON.stringify(next));
    } catch { add("p", "Could not save the new list in this browser."); return; }
    button.disabled = true;
    report(next, true);
  };
}
