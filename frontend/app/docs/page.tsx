"use client";

import { DragEvent, useCallback, useEffect, useMemo, useState } from "react";

const CONFIGURED_API = (process.env.NEXT_PUBLIC_API_URL || "").trim().replace(/\/$/, "");
const API = process.env.NODE_ENV === "development" ? (CONFIGURED_API || "http://localhost:8000") : CONFIGURED_API ? "/backend" : "";
type Section = { id: string; title: string; group: "pitch" | "product" | "engineering"; content: string };
type Member = { name: string; role: string; email: string; image_url: string };
type DocumentData = { title: string; team_name: string; tagline: string; summary: string; team_members: Member[]; sections: Section[] };
type Access = { enabled: boolean; start_at: string; end_at: string; repeat_yearly: boolean; timezone: "Asia/Dhaka" };
type Runtime = { checked_at: string; provider: string; model: string; provider_configured: boolean; workflow_nodes: string[]; features: Record<string, unknown>; api_endpoints: Array<{ method: string; path: string; purpose: string }> };
type AdminState = { draft: DocumentData; published: DocumentData; access: Access; updated_at: string; published_at: string; versions: Array<{ id: string; created_at: string; action: string }> };

const groupNames = { pitch: "Pitch deck", product: "Product", engineering: "Engineering" };

function safeText(value: string) {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function renderText(text: string) {
  return text.split(/\n\s*\n/).map((block, index) => {
    const lines = block.split("\n");
    const isList = lines.every((line) => /^\s*[-*]\s+/.test(line));
    const content = (line: string) => safeText(line.replace(/^\s*[-*]\s+/, ""))
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, "<code>$1</code>");
    if (isList) return <ul className="docs-list" key={index}>{lines.map((line, item) => <li key={item} dangerouslySetInnerHTML={{ __html: content(line) }} />)}</ul>;
    if (/^\|/.test(block.trim())) return <pre className="docs-pre" key={index}>{block}</pre>;
    return <p className="docs-copy" key={index} dangerouslySetInnerHTML={{ __html: lines.map(content).join("<br />") }} />;
  });
}

function initials(name: string) {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]?.toUpperCase()).join("") || "LC";
}

function DhakaDate({ value }: { value: string }) {
  const date = new Date(value);
  return <>{Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Dhaka" }).format(date)} Dhaka time</>;
}

function dateField(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Dhaka", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(date);
  const at = (type: string) => parts.find((part) => part.type === type)?.value || "00";
  return `${at("year")}-${at("month")}-${at("day")}T${at("hour")}:${at("minute")}`;
}

function Architecture() {
  const labels = ["Browser UI", "Next.js", "FastAPI", "In-memory session", "Parse + segment", "Risk and research graph", "Source + quote checks", "Assessment"];
  return <div className="docs-diagram" role="img" aria-label={labels.join(" to ")}>
    {labels.map((label, index) => <div className="docs-diagram-step" key={label}><span>{String(index + 1).padStart(2, "0")}</span><strong>{label}</strong>{index < labels.length - 1 && <i aria-hidden="true">↓</i>}</div>)}
  </div>;
}

function AdminPanel({ onClose }: { onClose: () => void }) {
  const [token, setToken] = useState("");
  const [admin, setAdmin] = useState<AdminState | null>(null);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [dragged, setDragged] = useState<string | null>(null);

  const request = useCallback(async (path: string, init?: RequestInit) => {
    if (!API) throw new Error("Backend URL is not configured.");
    const headers = new Headers(init?.headers);
    if (init?.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
    const response = await fetch(`${API}/docs${path}`, { ...init, cache: "no-store", credentials: "include", headers });
    let payload: any = null;
    try { payload = await response.json(); } catch { /* response has no JSON body */ }
    if (!response.ok) throw new Error(payload?.detail || `Request failed (${response.status}).`);
    return payload;
  }, []);

  const loadAdmin = useCallback(async () => {
    try { setAdmin(await request("/admin")); setStatus(""); }
    catch (error) { setStatus(error instanceof Error ? error.message : "Could not load admin settings."); }
  }, [request]);

  useEffect(() => { void loadAdmin(); }, [loadAdmin]);

  const updateDraft = (change: (draft: DocumentData) => DocumentData) => setAdmin((previous) => previous ? { ...previous, draft: change(previous.draft) } : previous);
  const login = async () => {
    setBusy(true);
    try { await request("/admin/session", { method: "POST", body: JSON.stringify({ token }) }); setToken(""); await loadAdmin(); }
    catch (error) { setStatus(error instanceof Error ? error.message : "Login failed."); }
    finally { setBusy(false); }
  };
  const saveDraft = async () => {
    if (!admin) return;
    setBusy(true);
    try { const result = await request("/admin/draft", { method: "PUT", body: JSON.stringify(admin.draft) }); setAdmin(result); setStatus("Draft saved. It is not public until published."); }
    catch (error) { setStatus(error instanceof Error ? error.message : "Could not save draft."); }
    finally { setBusy(false); }
  };
  const publish = async () => {
    setBusy(true);
    try { const result = await request("/admin/publish", { method: "POST" }); setAdmin(result); setStatus("Published version updated."); }
    catch (error) { setStatus(error instanceof Error ? error.message : "Could not publish."); }
    finally { setBusy(false); }
  };
  const logout = async () => {
    try { await request("/admin/session", { method: "DELETE" }); setStatus("Signed out."); }
    catch (error) { setStatus(error instanceof Error ? error.message : "Could not sign out cleanly."); }
    finally { setAdmin(null); }
  };
  const saveAccess = async () => {
    if (!admin) return;
    setBusy(true);
    const access = { ...admin.access, start_at: `${dateField(admin.access.start_at)}:00+06:00`, end_at: `${dateField(admin.access.end_at)}:00+06:00`, timezone: "Asia/Dhaka" };
    try { const result = await request("/admin/access", { method: "PUT", body: JSON.stringify(access) }); setAdmin(result); setStatus("Visibility and schedule saved."); }
    catch (error) { setStatus(error instanceof Error ? error.message : "Could not save the schedule."); }
    finally { setBusy(false); }
  };
  const moveSection = (fromId: string, toId: string) => updateDraft((draft) => {
    const list = [...draft.sections];
    const from = list.findIndex((item) => item.id === fromId);
    const to = list.findIndex((item) => item.id === toId);
    if (from < 0 || to < 0) return draft;
    const [item] = list.splice(from, 1); list.splice(to, 0, item);
    return { ...draft, sections: list };
  });

  return <div className="docs-admin-backdrop"><section className="docs-admin" aria-label="Documentation admin panel">
    <div className="docs-admin-top"><div><span className="docs-kicker">Protected workspace</span><h2>Documentation admin</h2></div><button className="docs-button docs-button-light" onClick={onClose}>Close</button></div>
    {!admin ? <div className="docs-card docs-login"><p>Enter the backend <code>DOCS_ADMIN_TOKEN</code>. The token is held in an HTTP-only session cookie for up to 8 hours.</p><label>Admin token<input type="password" autoComplete="current-password" value={token} onChange={(event) => setToken(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void login(); }} /></label><button className="docs-button docs-button-primary" disabled={busy || !token} onClick={() => void login()}>{busy ? "Signing in…" : "Sign in"}</button></div> : <>
      <div className="docs-admin-grid"><section className="docs-card"><h3>Public visibility</h3><label className="docs-toggle"><input type="checkbox" checked={admin.access.enabled} onChange={(event) => setAdmin({ ...admin, access: { ...admin.access, enabled: event.target.checked } })} /><span>Allow public access during the schedule</span></label><label>Window starts (Dhaka time)<input type="datetime-local" value={dateField(admin.access.start_at)} onChange={(event) => setAdmin({ ...admin, access: { ...admin.access, start_at: `${event.target.value}:00+06:00` } })} /></label><label>Window ends (Dhaka time)<input type="datetime-local" value={dateField(admin.access.end_at)} onChange={(event) => setAdmin({ ...admin, access: { ...admin.access, end_at: `${event.target.value}:00+06:00` } })} /></label><label className="docs-toggle"><input type="checkbox" checked={admin.access.repeat_yearly} onChange={(event) => setAdmin({ ...admin, access: { ...admin.access, repeat_yearly: event.target.checked } })} /><span>Repeat this June window every year</span></label><button className="docs-button docs-button-primary" disabled={busy} onClick={() => void saveAccess()}>Save visibility schedule</button></section>
      <section className="docs-card"><h3>Draft publishing</h3><p>Save changes as a draft, then publish when ready. Public visibility still follows the schedule above.</p><div className="docs-button-row"><button className="docs-button" disabled={busy} onClick={() => void saveDraft()}>Save draft</button><button className="docs-button docs-button-primary" disabled={busy} onClick={() => void publish()}>Publish draft</button><button className="docs-button docs-button-danger" onClick={() => void logout()}>Sign out</button></div><small>Last saved: <DhakaDate value={admin.updated_at} /></small><h4>Version history</h4><ul className="docs-versions">{admin.versions.map((version) => <li key={version.id}><strong>{version.action.replaceAll("-", " ")}</strong><span><DhakaDate value={version.created_at} /></span></li>)}</ul></section></div>
      <section className="docs-card docs-editor"><div className="docs-editor-heading"><div><h3>Pitch and documentation content</h3><p>Drag sections to reorder, edit copy, then save and publish.</p></div><button className="docs-button" onClick={() => updateDraft((draft) => ({ ...draft, sections: [...draft.sections, { id: `custom-${Date.now()}`, title: "New section", group: "engineering", content: "Add documentation copy." }] }))}>Add section</button></div>
        <div className="docs-admin-grid"><label>Project title<input value={admin.draft.title} onChange={(event) => updateDraft((draft) => ({ ...draft, title: event.target.value }))} /></label><label>Team name<input value={admin.draft.team_name} onChange={(event) => updateDraft((draft) => ({ ...draft, team_name: event.target.value }))} /></label><label className="docs-wide">Tagline<input value={admin.draft.tagline} onChange={(event) => updateDraft((draft) => ({ ...draft, tagline: event.target.value }))} /></label><label className="docs-wide">Public summary<textarea rows={3} value={admin.draft.summary} onChange={(event) => updateDraft((draft) => ({ ...draft, summary: event.target.value }))} /></label></div>
        <div className="docs-member-editor"><div className="docs-editor-heading"><h4>Team showcase</h4><button className="docs-button" onClick={() => updateDraft((draft) => ({ ...draft, team_members: [...draft.team_members, { name: "", role: "", email: "", image_url: "" }] }))}>Add member</button></div>{admin.draft.team_members.map((member, index) => <div className="docs-member-row" key={index}><input aria-label="Member name" placeholder="Full name" value={member.name} onChange={(event) => updateDraft((draft) => ({ ...draft, team_members: draft.team_members.map((item, i) => i === index ? { ...item, name: event.target.value } : item) }))} /><input aria-label="Member role" placeholder="Role" value={member.role} onChange={(event) => updateDraft((draft) => ({ ...draft, team_members: draft.team_members.map((item, i) => i === index ? { ...item, role: event.target.value } : item) }))} /><input aria-label="Member email" placeholder="Email" value={member.email} onChange={(event) => updateDraft((draft) => ({ ...draft, team_members: draft.team_members.map((item, i) => i === index ? { ...item, email: event.target.value } : item) }))} /><input aria-label="Member image URL" placeholder="Profile image URL (optional)" value={member.image_url} onChange={(event) => updateDraft((draft) => ({ ...draft, team_members: draft.team_members.map((item, i) => i === index ? { ...item, image_url: event.target.value } : item) }))} /><button className="docs-button docs-button-danger" onClick={() => updateDraft((draft) => ({ ...draft, team_members: draft.team_members.filter((_, i) => i !== index) }))}>Remove</button></div>)}</div>
        <div className="docs-section-editor">{admin.draft.sections.map((section, index) => <article className="docs-edit-section" key={section.id} draggable onDragStart={() => setDragged(section.id)} onDragOver={(event: DragEvent) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); if (dragged) moveSection(dragged, section.id); setDragged(null); }} onDragEnd={() => setDragged(null)}><div className="docs-edit-section-head"><span className="docs-drag" title="Drag to reorder">⠿</span><span className="docs-group-chip">{groupNames[section.group]}</span><strong>{index + 1}. {section.title}</strong><div className="docs-move"><button aria-label="Move section up" disabled={index === 0} onClick={() => moveSection(section.id, admin.draft.sections[index - 1].id)}>↑</button><button aria-label="Move section down" disabled={index === admin.draft.sections.length - 1} onClick={() => moveSection(section.id, admin.draft.sections[index + 1].id)}>↓</button><button aria-label="Remove section" onClick={() => updateDraft((draft) => ({ ...draft, sections: draft.sections.filter((item) => item.id !== section.id) }))}>×</button></div></div><label>Section title<input value={section.title} onChange={(event) => updateDraft((draft) => ({ ...draft, sections: draft.sections.map((item) => item.id === section.id ? { ...item, title: event.target.value } : item) }))} /></label><label>Section group<select value={section.group} onChange={(event) => updateDraft((draft) => ({ ...draft, sections: draft.sections.map((item) => item.id === section.id ? { ...item, group: event.target.value as Section["group"] } : item) }))}><option value="pitch">Pitch deck</option><option value="product">Product</option><option value="engineering">Engineering</option></select></label><label>Section copy<textarea rows={4} value={section.content} onChange={(event) => updateDraft((draft) => ({ ...draft, sections: draft.sections.map((item) => item.id === section.id ? { ...item, content: event.target.value } : item) }))} /></label><div className="docs-inline-preview"><span>Preview</span><p>{section.content}</p></div></article>)}</div>
      </section>
      <p className="docs-admin-note">Public content is served only when visibility is enabled and the schedule window is active. The admin route is always token-protected.</p>
    </>}
    {status && <p className="docs-toast" role="status">{status}</p>}
  </section></div>;
}

export default function DocsPage() {
  const [data, setData] = useState<{ document: DocumentData; live: Runtime; published_at: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [available, setAvailable] = useState(true);
  const [query, setQuery] = useState("");
  const [adminOpen, setAdminOpen] = useState(false);

  const refresh = useCallback(async () => {
    if (!API) { setAvailable(false); setLoading(false); return; }
    try {
      const response = await fetch(`${API}/docs`, { cache: "no-store" });
      if (!response.ok) { setAvailable(false); return; }
      setData(await response.json()); setAvailable(true);
    } catch { setAvailable(false); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    void refresh();
    setAdminOpen(new URLSearchParams(window.location.search).get("admin") === "1");
    const timer = window.setInterval(() => void refresh(), 60_000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const sections = data?.document.sections || [];
  const visibleSections = useMemo(() => {
    if (!query.trim()) return sections;
    const needle = query.toLowerCase();
    return sections.filter((section) => `${section.title} ${section.content}`.toLowerCase().includes(needle));
  }, [sections, query]);
  const grouped = ["pitch", "product", "engineering"] as const;
  const itemsByGroup = (group: typeof grouped[number]) => visibleSections.filter((section) => section.group === group);

  if (loading) return <main className="docs-loading"><span className="docs-spinner" />Loading project documentation…</main>;
  if (!available || !data) return <main className="docs-unavailable"><div className="docs-lock-icon">LC</div><span className="docs-kicker">Legal Copilot showcase</span><h1>Documentation isn’t available right now.</h1><p>The publishing window may be closed, the page may be unpublished, or the API could not be reached.</p><a className="docs-button docs-button-light" href="/">Return to Legal Copilot</a><a className="docs-admin-link" href="/docs?admin=1">Admin access</a>{adminOpen && <AdminPanel onClose={() => setAdminOpen(false)} />}</main>;

  return <main className="docs-shell">
    <header className="docs-topbar"><a className="docs-brand" href="/"><span className="docs-lock-icon">LC</span><span><strong>{data.document.title}</strong><small>Pitch deck · Product docs · Live system view</small></span></a><div className="docs-top-actions"><a className="docs-text-link" href="/">Open app</a><a className="docs-button docs-button-light" href={`${API}/docs/export.md`}>Export Markdown</a><button className="docs-button docs-button-light" onClick={() => window.print()}>Print / PDF</button><button className="docs-button docs-button-dark" onClick={() => setAdminOpen(true)}>Admin</button></div></header>
    <section className="docs-hero"><div className="docs-hero-copy"><span className="docs-kicker">{data.document.team_name || "JusticeSphere AI"} · Legal technology</span><h1>{data.document.title}</h1><p className="docs-tagline">{data.document.tagline}</p><p className="docs-summary">{data.document.summary}</p><div className="docs-hero-actions"><a href="#problem" className="docs-button docs-button-dark">Explore the pitch</a><span className="docs-live-pill"><i /> Live project configuration</span></div></div><div className="docs-hero-card"><div className="docs-card-label">System snapshot</div><strong>{data.live.provider}</strong><p>{data.live.model}</p><div className="docs-snapshot-line"><span>Provider configured</span><b className={data.live.provider_configured ? "docs-good" : "docs-warn"}>{data.live.provider_configured ? "Yes" : "Needs setup"}</b></div><div className="docs-snapshot-line"><span>Model calls</span><b>Backend configured</b></div><div className="docs-snapshot-line"><span>Analytics</span><b>Not collected</b></div><small>Refreshed <DhakaDate value={data.live.checked_at} /></small></div></section>
    <div className="docs-layout"><aside className="docs-sidebar"><label className="docs-search"><span>⌕</span><input placeholder="Search documentation" value={query} onChange={(event) => setQuery(event.target.value)} /></label><p className="docs-nav-title">ON THIS PAGE</p>{grouped.map((group) => <div className="docs-nav-group" key={group}><span>{groupNames[group]}</span>{itemsByGroup(group).map((section) => <a key={section.id} href={`#${section.id}`}>{section.title}</a>)}</div>)}<div className="docs-sidebar-foot"><span className="docs-live-dot" /> Published <DhakaDate value={data.published_at} /></div></aside>
      <div className="docs-content">
        <section className="docs-section docs-quick-view"><span className="docs-kicker">In two minutes</span><h2>Contract triage that keeps evidence in view.</h2><p>{data.document.summary}</p><div className="docs-pill-row"><span>Clause-level review</span><span>Exact quote checks</span><span>Coverage warnings</span><span>Counsel handoff</span></div></section>
        {grouped.map((group) => <div key={group} className="docs-group-block"><p className="docs-group-heading">{groupNames[group]}</p>{itemsByGroup(group).map((section) => <section className="docs-section" id={section.id} key={section.id}><div className="docs-section-title"><span>{section.group === "pitch" ? "01" : section.group === "product" ? "02" : "03"}</span><div><p>{groupNames[section.group]}</p><h2>{section.title}</h2></div></div>{section.id === "architecture" ? <><p className="docs-copy">{section.content}</p><Architecture /></> : section.id === "data-flow" ? <><p className="docs-copy">{section.content}</p><div className="docs-flow">{["Input", "Processing", "AI", "Output", "Purge / TTL"].map((step, index) => <div key={step}><span>0{index + 1}</span><strong>{step}</strong></div>)}</div></> : section.id === "team" || section.id === "contributors" ? <><p className="docs-copy">{section.content}</p>{data.document.team_members.length ? <div className="docs-team-grid">{data.document.team_members.map((member) => <article className="docs-team-card" key={`${member.email}-${member.name}`}>{member.image_url ? <img src={member.image_url} alt="" className="docs-avatar" onError={(event) => { event.currentTarget.style.display = "none"; event.currentTarget.nextElementSibling?.classList.remove("docs-hidden"); }} /> : null}<div className={`docs-avatar docs-avatar-fallback ${member.image_url ? "docs-hidden" : ""}`}>{initials(member.name)}</div><h3>{member.name}</h3><p>{member.role}</p><a href={`mailto:${member.email}`}>{member.email}</a></article>)}</div> : <div className="docs-empty-team">Team profiles will appear here when approved details are added.</div>}</> : section.id === "features" ? <><p className="docs-copy">{section.content}</p><div className="docs-feature-grid">{Object.entries(data.live.features).map(([key, value]) => <div className="docs-feature-row" key={key}><span>{key.replaceAll("_", " ")}</span><b>{typeof value === "boolean" ? value ? "Enabled" : "Not configured" : Array.isArray(value) ? value.join(", ") : String(value)}</b></div>)}</div></> : section.id === "api" ? <><p className="docs-copy">{section.content}</p><div className="docs-api-list">{data.live.api_endpoints.map((endpoint) => <div key={`${endpoint.method}-${endpoint.path}`}><code>{endpoint.method}</code><code>{endpoint.path}</code><span>{endpoint.purpose}</span></div>)}</div><a className="docs-inline-link" href={`${API}/openapi.json`} target="_blank" rel="noreferrer">OpenAPI schema ↗</a></> : renderText(section.content)}</section>)}</div>)}
        <footer className="docs-footer"><strong>Legal Copilot is a preliminary review aid, not legal advice.</strong><span>Verify findings, extracted text, sources, and jurisdiction with qualified counsel.</span><div><a href="/">Return to app</a><a href={`${API}/docs/export.md`}>Markdown</a><button onClick={() => window.print()}>Print / Save PDF</button></div></footer>
      </div></div>
    {adminOpen && <AdminPanel onClose={() => { setAdminOpen(false); void refresh(); }} />}
  </main>;
}
