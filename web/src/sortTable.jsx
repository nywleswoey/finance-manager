import React from "react";

/**
 * Click-to-sort for a plain HTML table: `sortRows` orders the rows, `SortTh` is the header cell
 * that drives it (keyboard-reachable, `aria-sort` set). One copy, shared by any table that sorts.
 */
// Click-to-sort table header: numeric columns default to descending (biggest first) on their
// first click, text columns to ascending (A→Z) — `defaultDir` lets a caller flip that per
// column. A null/undefined value (the yield columns' dash) always sorts last in either
// direction, so `sortRows` never has to be told which columns can hold one.
export function sortRows(rows, sort) {
  if (!sort.key) return rows;
  const dirMul = sort.dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const av = a[sort.key], bv = b[sort.key];
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    return typeof av === "string" ? dirMul * av.localeCompare(bv) : dirMul * (av - bv);
  });
}

export function SortTh({ sortKey, label, defaultDir, sort, onSort, className, title }) {
  const active = sort.key === sortKey;
  const ariaSort = active ? (sort.dir === "asc" ? "ascending" : "descending") : "none";
  const activate = () => onSort(sortKey, defaultDir);
  return (
    <th className={className} title={title} role="columnheader" aria-sort={ariaSort}
        tabIndex={0} style={{ cursor: "pointer" }}
        onClick={activate}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); activate(); } }}>
      {label}
      {active && <span aria-hidden="true" style={{ marginLeft: 4 }}>{sort.dir === "asc" ? "▲" : "▼"}</span>}
    </th>
  );
}
