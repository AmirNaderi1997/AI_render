import React from "react";
import { api, type EffectPreset, type LearnedStyleProfile, type PlanStyleSelection, type RafieiStyle, type StyleLibraryData } from "./api";
import { LoadingState, friendlyError } from "./ui";

const ENERGY_COLORS: Record<number, string> = {
  5: "#f87171", 4: "#fb923c", 3: "#fbbf24", 2: "#34d399", 1: "#60a5fa",
};
const hintColor = (effect: EffectPreset) => effect.hint_color || ENERGY_COLORS[effect.energy ?? 3] || "#94a3b8";
const styleSourceIcon = (type?: string) => type === "snapshots" ? "▦" : type === "reference_video" ? "▶" : type === "style_file" ? "{ }" : "✦";

async function fetchMyEffects() {
  return api.getMyEffects();
}

async function saveMyEffects(data: any) {
  return api.putMyEffects(data);
}

export default function MyEffects() {
  const [effects, setEffects] = React.useState<EffectPreset[]>([]);
  const [myEffects, setMyEffects] = React.useState<any>(null);
  const [rafiei, setRafiei] = React.useState<RafieiStyle | null>(null);
  const [styleLibrary, setStyleLibrary] = React.useState<StyleLibraryData>({ drafts: [], profiles: [] });
  const [learnedProfile, setLearnedProfile] = React.useState<LearnedStyleProfile | null>(null);
  const [selectingRafiei, setSelectingRafiei] = React.useState<string | null>(null);
  const [planStyleSelection, setPlanStyleSelection] = React.useState<PlanStyleSelection | null>(null);
  const [selectingPlanStyle, setSelectingPlanStyle] = React.useState<string | null>(null);
  const [error, setError] = React.useState("");
  const [newRule, setNewRule] = React.useState("");
  const [loading, setLoading] = React.useState(true);
  const [pendingActions, setPendingActions] = React.useState(0);
  async function track<T>(action: () => Promise<T>): Promise<T> {
    setPendingActions(count => count + 1);
    try { return await action(); }
    finally { setPendingActions(count => count - 1); }
  }

  const reload = React.useCallback(async () => {
    try {
      setMyEffects(await fetchMyEffects());
    } catch (e) {
      setError(friendlyError(e, "load your effects"));
    }
  }, []);
  const reloadStyles = React.useCallback(async () => {
    try { setStyleLibrary(await api.getStyleLibrary()); }
    catch (e) { setError(friendlyError(e, "load styles")); }
  }, []);

  React.useEffect(() => {
    Promise.all([
      api.listEffects().then(setEffects),
      fetchMyEffects().then(setMyEffects),
      api.getRafieiStyles().then(setRafiei),
      api.getStyleLibrary().then(setStyleLibrary),
      api.getPlanStyleSelection().then(setPlanStyleSelection),
      api.getLearnedProfile().then(setLearnedProfile),
    ]).catch(e => setError(friendlyError(e, "load your effects"))).finally(() => setLoading(false));
  }, []);

  async function handleSelectRafiei(styleId: string) {
    if (!myEffects) return;
    setSelectingRafiei(styleId); setError("");
    try {
      const next = myEffects.selected_rafiei_style === styleId ? null : styleId;
      await track(() => api.selectRafieiStyle(next));
      await reload();
    } catch (e) { setError(friendlyError(e, "update your effects")); }
    finally { setSelectingRafiei(null); }
  }

  async function handleSelectPlanStyle(styleId: string | null, version: number | null) {
    const key = styleId ? `${styleId}@${version}` : "learned";
    setSelectingPlanStyle(key); setError("");
    try {
      const saved = await track(() => styleId ? api.setPlanStyleSelection(styleId, version) : api.clearPlanStyleSelection());
      setPlanStyleSelection(saved);
    } catch (e) { setError(friendlyError(e, "save your default plan style")); }
    finally { setSelectingPlanStyle(null); }
  }

  async function handleUsePlanDefaults() {
    setSelectingPlanStyle("default"); setError("");
    try {
      if (learnedProfile?.enabled) await track(() => api.updateLearnedProfile({ enabled: false }));
      const [selection, profile] = await Promise.all([
        track(() => defaultsSelected ? api.clearPlanStyleSelection() : api.setPlanStyleSelection(null, null)),
        api.getLearnedProfile(),
      ]);
      setPlanStyleSelection(selection);
      setLearnedProfile(profile);
    } catch (e) { setError(friendlyError(e, "use the default plan style")); }
    finally { setSelectingPlanStyle(null); }
  }

  async function handleDeletePlanDefaults() {
    if (!window.confirm("Hide Rafiei Reel defaults from My Effects? The built-in rendering preset will remain available. You can restore this card later.")) return;
    setSelectingPlanStyle("default-delete"); setError("");
    try {
      await track(() => api.setPlanDefaultVisibility(true));
      setPlanStyleSelection(await api.getPlanStyleSelection());
    } catch (e) { setError(friendlyError(e, "hide the default plan style")); }
    finally { setSelectingPlanStyle(null); }
  }

  async function handleRestorePlanDefaults() {
    setSelectingPlanStyle("default-restore"); setError("");
    try {
      await track(() => api.setPlanDefaultVisibility(false));
      setPlanStyleSelection(await api.getPlanStyleSelection());
    } catch (e) { setError(friendlyError(e, "restore the default plan style")); }
    finally { setSelectingPlanStyle(null); }
  }

  async function handleToggleLearnedProfile() {
    if (!learnedProfile?.active) return;
    setSelectingPlanStyle("learned"); setError("");
    try {
      const enable = !learnedSelected;
      await track(() => api.updateLearnedProfile({ enabled: enable }));
      const [selection, profile] = await Promise.all([
        enable ? track(() => api.clearPlanStyleSelection()) : Promise.resolve(planStyleSelection),
        api.getLearnedProfile(),
      ]);
      if (selection) setPlanStyleSelection(selection);
      setLearnedProfile(profile);
    } catch (e) { setError(friendlyError(e, "update the learned plan style")); }
    finally { setSelectingPlanStyle(null); }
  }

  async function handleDeleteLearnedProfile() {
    if (!window.confirm("Delete the learned profile? Reference reels will be kept so you can rebuild it later.")) return;
    setSelectingPlanStyle("learned-delete"); setError("");
    try {
      await track(() => api.resetLearnedProfile());
      const [selection, profile] = await Promise.all([
        api.setPlanStyleSelection(null, null),
        api.getLearnedProfile(),
      ]);
      setPlanStyleSelection(selection);
      setLearnedProfile(profile);
    } catch (e) { setError(friendlyError(e, "delete the learned profile")); }
    finally { setSelectingPlanStyle(null); }
  }

  async function handleAddRule() {
    if (!newRule.trim() || !myEffects) return;
    setError("");
    try {
      const updated = {
        ...myEffects,
        rules: [...myEffects.rules, { text: newRule.trim(), priority: "hard" }],
      };
      await track(() => saveMyEffects(updated));
      setNewRule("");
      await reload();
    } catch (e) { setError(friendlyError(e, "update your effects")); }
  }

  async function handleRemoveRule(index: number) {
    if (!myEffects) return;
    setError("");
    try {
      const updated = {
        ...myEffects,
        rules: myEffects.rules.filter((_: any, i: number) => i !== index),
      };
      await track(() => saveMyEffects(updated));
      await reload();
    } catch (e) { setError(friendlyError(e, "update your effects")); }
  }

  async function handleToggleFavorite(effectId: string) {
    if (!myEffects) return;
    setError("");
    try {
      const updated = { ...myEffects, favorites: { ...myEffects.favorites } };
      if (updated.favorites[effectId]) {
        delete updated.favorites[effectId];
      } else {
        updated.favorites[effectId] = { weight: 1.0, tags: [] };
      }
      await track(() => saveMyEffects(updated));
      await reload();
    } catch (e) { setError(friendlyError(e, "update your effects")); }
  }

  async function handleWeightChange(effectId: string, weight: number) {
    if (!myEffects) return;
    try {
      const updated = {
        ...myEffects,
        favorites: {
          ...myEffects.favorites,
          [effectId]: { ...myEffects.favorites[effectId], weight },
        },
      };
      await track(() => saveMyEffects(updated));
      await reload();
    } catch (e) { setError(friendlyError(e, "update your effects")); }
  }

  async function handleDeleteProfile(styleId: string, version: number, name: string) {
    if (!window.confirm(`Remove "${name} · v${version}" from My Effects? Existing jobs will keep their pinned version.`)) return;
    setError("");
    try {
      await track(() => api.deleteStyleProfile(styleId, version));
      const [styles, selection] = await Promise.all([
        api.getStyleLibrary(),
        api.getPlanStyleSelection(),
      ]);
      setStyleLibrary(styles);
      setPlanStyleSelection(selection);
    }
    catch (e) { setError(friendlyError(e, "update your effects")); }
  }

  async function handleDeleteDraft(id: string, name: string) {
    if (!window.confirm(`Delete the imported style draft "${name}"?`)) return;
    setError("");
    try { await track(() => api.deleteStyleDraft(id)); await reloadStyles(); }
    catch (e) { setError(friendlyError(e, "update your effects")); }
  }

  if (loading) return <LoadingState label="Loading effects…" />;
  if (!myEffects) return <div className="errors" role="alert">{error || "We could not load your effects."} <button className="secondary" onClick={() => window.location.reload()}>Try again</button></div>;

  const selectedRafieiStyle = myEffects.selected_rafiei_style as string | null;
  const learnedSelected = Boolean(!planStyleSelection?.style_id && learnedProfile?.active && learnedProfile?.enabled);
  const defaultsSelected = Boolean(planStyleSelection?.selected && !planStyleSelection.style_id && !learnedSelected);
  const learnedProfileExists = Boolean(learnedProfile?.exists);
  return (
    <div>
      <h1>My Effects</h1>
      {pendingActions > 0 && <p className="muted" role="status">Saving your effects…</p>}
      {error && <div className="errors" role="alert" style={{ marginBottom: 16 }}>{error}</div>}

      {rafiei && <section style={{ marginBottom: 32 }}>
        <h2>Rafiei Styles</h2>
        <p className="muted" style={{ marginBottom: 12 }}>Choose one style. Your selection is separate from Favorites and My Rules.</p>
        <div className="rafiei-style-grid">
          {rafiei.preferred_effects.map(id => {
            const eff = effects.find(item => item.id === id);
            if (!eff) return null;
            const selected = selectedRafieiStyle === id;
            return <button
              key={id}
              type="button"
              className={`rafiei-style-card${selected ? " is-selected" : ""}`}
              style={{
                borderLeftColor: hintColor(eff),
              }}
              aria-pressed={selected}
              disabled={selectingRafiei !== null}
              onClick={() => handleSelectRafiei(id)}
              title={eff.description}
            >
              <span className="rafiei-style-card__header">
                <span className="rafiei-style-card__title">{eff.label}</span>
                <span className="rafiei-style-card__check" aria-hidden="true">
                  {selectingRafiei === id ? "..." : selected ? "✓" : ""}
                </span>
              </span>
              {eff.mood && <span className="rafiei-style-card__mood" style={{ color: hintColor(eff) }}>{eff.mood}</span>}
              <span className="rafiei-style-card__description">{eff.description}</span>
              <span className="rafiei-style-card__action">
                {selected ? "Selected · Click to clear" : "Select this style"}
              </span>
            </button>;
          })}
        </div>
      </section>}

      <section style={{ marginBottom: 32 }}>
        <div className="section-header">
          <h2>Plan styles</h2>
          <a href="/style-library" style={{ fontSize: 13 }}>Manage styles</a>
        </div>
        <p className="muted" style={{ marginBottom: 12 }}>
          Choose the default style for new plans. Existing plans keep their selected version; you can change this default any time.
          Choosing Learned profile uses your Style Learner profile when it is enabled.
        </p>
        <div className="rafiei-style-grid">
          {!planStyleSelection?.default_hidden && <div className="plan-style-card-wrap">
          <button type="button" className={`rafiei-style-card${defaultsSelected ? " is-selected" : ""}`}
            aria-pressed={defaultsSelected} disabled={selectingPlanStyle !== null || pendingActions > 0}
            onClick={() => void handleUsePlanDefaults()}>
            <span className="rafiei-style-card__header"><span className="rafiei-style-card__title">Rafiei Reel defaults</span>
              <span className="rafiei-style-card__check" aria-hidden="true">{selectingPlanStyle === "default" ? "…" : defaultsSelected ? "✓" : ""}</span></span>
            <span className="rafiei-style-card__description">Use the built-in Rafiei Reel plan style without a learned or imported override.</span>
            <span className="rafiei-style-card__action">{defaultsSelected ? "Selected · Click to deselect" : "Select defaults"}</span>
          </button>
          <button type="button" className="danger-sm plan-style-card__delete"
            disabled={selectingPlanStyle !== null || pendingActions > 0}
            onClick={() => void handleDeletePlanDefaults()}
            aria-label="Delete Rafiei Reel defaults from My Effects"
            title="Hide this card; the built-in rendering preset remains available">Delete</button>
          </div>}
          <div className="plan-style-card-wrap">
            <button type="button" className={`rafiei-style-card${learnedSelected ? " is-selected" : ""}`}
              aria-pressed={learnedSelected} disabled={selectingPlanStyle !== null || pendingActions > 0 || !learnedProfile?.active}
              onClick={() => void handleToggleLearnedProfile()}>
              <span className="rafiei-style-card__header"><span className="rafiei-style-card__title">Learned profile</span>
                <span className="rafiei-style-card__check" aria-hidden="true">{selectingPlanStyle === "learned" ? "…" : learnedSelected ? "✓" : ""}</span></span>
              <span className="rafiei-style-card__description">Use the profile learned from your reference reels for new plans.</span>
              <span className="rafiei-style-card__action">{!learnedProfile?.active ? "Needs at least 3 reference reels" : learnedSelected ? "Selected · Click to deselect" : "Select learned profile"}</span>
            </button>
            <button type="button" className="danger-sm plan-style-card__delete"
              disabled={selectingPlanStyle !== null || pendingActions > 0 || !learnedProfileExists}
              onClick={() => void handleDeleteLearnedProfile()}
              aria-label="Delete learned profile"
              title="Delete the learned profile; reference reels are kept">Delete</button>
          </div>
          {styleLibrary.profiles.map(profile => {
            const key = `${profile.style_id}@${profile.version}`;
            const selected = planStyleSelection?.style_id === profile.style_id && planStyleSelection?.version === profile.version;
            return <div key={key} className="plan-style-card-wrap">
              <button type="button" className={`rafiei-style-card${selected ? " is-selected" : ""}`}
                aria-pressed={selected} disabled={selectingPlanStyle !== null || pendingActions > 0}
                onClick={() => void handleSelectPlanStyle(
                  selected ? null : profile.style_id,
                  selected ? null : profile.version,
                )}>
                <span className="rafiei-style-card__header"><span className="rafiei-style-card__title">{profile.name} · v{profile.version}</span>
                  <span className="rafiei-style-card__check" aria-hidden="true">{selectingPlanStyle === key ? "…" : selected ? "✓" : ""}</span></span>
                <span className="rafiei-style-card__mood">{(profile.source?.type || "imported").replace(/_/g, " ")}</span>
                <span className="rafiei-style-card__description">Apply this approved imported style to new plans. Existing jobs keep their current style.</span>
                <span className="rafiei-style-card__action">{selected ? "Selected · Click to deselect" : "Select this style"}</span>
              </button>
              <button type="button" className="danger-sm plan-style-card__delete"
                disabled={selectingPlanStyle !== null || pendingActions > 0}
                onClick={() => void handleDeleteProfile(profile.style_id, profile.version, profile.name)}
                aria-label={`Delete ${profile.name} version ${profile.version}`}
                title="Delete this saved plan style">Delete</button>
            </div>;
          })}
        </div>
        {planStyleSelection?.default_hidden && <p className="muted" style={{ marginTop: 10 }}>
          Rafiei Reel defaults is hidden from My Effects. <button type="button" className="link-button"
            disabled={selectingPlanStyle !== null || pendingActions > 0}
            onClick={() => void handleRestorePlanDefaults()}>Restore card</button>
        </p>}
        {!loading && !styleLibrary.profiles.length && <p className="muted" style={{ marginTop: 10 }}>No approved styles yet. Import and approve one in <a href="/style-library">Styles &amp; Fonts Library</a>.</p>}
      </section>

      <section style={{ marginBottom: 32 }}>
        <div className="section-header">
          <h2>Imported Styles</h2>
          <a href="/style-library" style={{ fontSize: 13 }}>Open library</a>
        </div>
        <p className="muted" style={{ marginBottom: 12 }}>Drafts need approval before they can be used.</p>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 10 }}>
          {styleLibrary.profiles.map(profile => (
            <article key={`${profile.style_id}@${profile.version}`} style={{
              display: "flex", flexDirection: "column", gap: 6, padding: "14px 16px",
              background: "var(--surface)", border: "1px solid var(--border)",
              borderLeft: "4px solid var(--success)", borderRadius: "var(--radius-md)", minHeight: 140,
            }}>
              <span style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                <span style={{ display: "flex", alignItems: "center", gap: 8, flex: 1, minWidth: 0 }}>
                  <span style={{
                    width: 28, height: 28, borderRadius: 8, display: "inline-flex", alignItems: "center", justifyContent: "center",
                    background: "rgba(255,255,255,0.05)", border: "1px solid var(--border)", color: "var(--accent-hover)",
                    fontSize: 12, fontWeight: 800, flexShrink: 0
                  }}>{styleSourceIcon(profile.source?.type)}</span>
                  <span style={{ fontWeight: 700, fontSize: 14 }}>{profile.name}</span>
                </span>
                <span className="status-badge done">Approved</span>
              </span>
              <span className="muted" style={{ fontSize: 12 }}>v{profile.version} · {(profile.source?.type || "imported").replace(/_/g, " ")}</span>
              <span className="muted" style={{ fontSize: 12 }}>Ready to use in a new reel.</span>
              <span style={{ marginTop: "auto", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                <a href={`/new?style_id=${encodeURIComponent(profile.style_id)}&style_version=${profile.version}`}
                  style={{ fontSize: 12, fontWeight: 700 }}>Use style</a>
                <button type="button" className="danger-sm" onClick={() => void handleDeleteProfile(profile.style_id, profile.version, profile.name)}
                  aria-label={`Remove ${profile.name}`}>&#10005;</button>
              </span>
            </article>
          ))}
          {styleLibrary.drafts.filter(d => d.state === "draft").map(draft => (
            <article key={draft.id} style={{
              display: "flex", flexDirection: "column", gap: 6, padding: "14px 16px",
              background: "var(--surface)", border: "1px solid var(--border)",
              borderLeft: "4px solid var(--warning)", borderRadius: "var(--radius-md)", minHeight: 140,
            }}>
              <span style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                <span style={{ display: "flex", alignItems: "center", gap: 8, flex: 1, minWidth: 0 }}>
                  <span style={{
                    width: 28, height: 28, borderRadius: 8, display: "inline-flex", alignItems: "center", justifyContent: "center",
                    background: "rgba(255,255,255,0.05)", border: "1px solid var(--border)", color: "var(--accent-hover)",
                    fontSize: 12, fontWeight: 800, flexShrink: 0
                  }}>{styleSourceIcon(draft.source?.type)}</span>
                  <span style={{ fontWeight: 700, fontSize: 14 }}>{draft.name}</span>
                </span>
                <span style={{
                  padding: "3px 8px", borderRadius: 100, fontSize: 10, fontWeight: 700,
                  textTransform: "uppercase", background: "var(--warning-soft)", color: "var(--warning)"
                }}>Draft</span>
              </span>
              <span className="muted" style={{ fontSize: 12 }}>{(draft.source?.type || "imported").replace(/_/g, " ")}</span>
              <span className="muted" style={{ fontSize: 12 }}>Review the extracted profile before using it.</span>
              <span style={{ marginTop: "auto", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                <a href={`/style-library?draft=${encodeURIComponent(draft.id)}`}
                  style={{ fontSize: 12, fontWeight: 700 }}>Review style</a>
                <button type="button" className="danger-sm" onClick={() => void handleDeleteDraft(draft.id, draft.name)}
                  aria-label={`Delete ${draft.name}`}>&#10005;</button>
              </span>
            </article>
          ))}
        </div>
        {!styleLibrary.profiles.length && !styleLibrary.drafts.some(d => d.state === "draft") && (
          <div className="empty-state" style={{ padding: 32 }}>
            <p className="muted">No imported styles yet.</p>
            <a href="/style-library">Import a style</a>
          </div>
        )}
      </section>

      <section style={{ marginBottom: 32 }}>
        <h2>Favorites</h2>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 10 }}>
          {effects.map(eff => (
            <div
              key={eff.id}
              style={{
                borderLeft: `4px solid ${hintColor(eff)}`,
                border: `1px solid ${myEffects.favorites[eff.id] ? "rgba(251,191,36,0.3)" : "var(--border)"}`,
                borderLeftWidth: 4,
                borderLeftColor: hintColor(eff),
                borderRadius: "var(--radius-md)",
                padding: "12px 14px",
                cursor: "pointer",
                background: myEffects.favorites[eff.id] ? "var(--warning-soft)" : "var(--surface)",
                transition: "all 0.2s",
                position: "relative",
              }}
              title={`${eff.description}${eff.best_roles?.length ? `\nBest for: ${eff.best_roles.join(", ")}` : ""}`}
              onClick={() => handleToggleFavorite(eff.id)}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start" }}>
                <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 2 }}>{eff.label}</div>
                <button type="button" className="favorite-toggle" aria-pressed={Boolean(myEffects.favorites[eff.id])}
                  aria-label={`${myEffects.favorites[eff.id] ? "Remove" : "Add"} ${eff.label} ${myEffects.favorites[eff.id] ? "from" : "to"} favorites`}
                  onClick={e => { e.stopPropagation(); void handleToggleFavorite(eff.id); }}
                  style={{ fontSize: 20, color: myEffects.favorites[eff.id] ? "var(--warning)" : "var(--text-tertiary)" }}>
                  {myEffects.favorites[eff.id] ? "★" : "☆"}
                </button>
              </div>
              <span style={{
                display: "inline-block", padding: "1px 6px", borderRadius: 100,
                fontSize: 10, fontWeight: 600, background: "rgba(255,255,255,0.06)", color: hintColor(eff),
              }}>{eff.mood}</span>
              <div className="muted" style={{ fontSize: 12, marginTop: 4, lineHeight: 1.4 }}>{eff.description}</div>
              {myEffects.favorites[eff.id] && (
                <input
                  type="range"
                  aria-label={`Weight for ${eff.label}`}
                  min="0.5"
                  max="2"
                  step="0.1"
                  defaultValue={myEffects.favorites[eff.id].weight || 1.0}
                  onClick={e => e.stopPropagation()}
                  onChange={e => handleWeightChange(eff.id, parseFloat(e.target.value))}
                  style={{ width: "100%", marginTop: 8, cursor: "pointer" }}
                />
              )}
            </div>
          ))}
        </div>
      </section>

      <section>
        <h2>My Rules</h2>
        <div className="card">
          <div style={{ display: "flex", gap: 8, marginBottom: 14 }}>
            <input
              type="text"
              aria-label="New effect rule"
              placeholder="Add rule in Persian or English... (e.g., 'روی اعداد زوم سریع')"
              value={newRule}
              onChange={e => setNewRule(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter") handleAddRule(); }}
              style={{ flex: 1 }}
            />
            <button onClick={handleAddRule}>Add</button>
          </div>
          {myEffects.rules.length === 0 && (
            <div className="empty-state" style={{ padding: "24px 0" }}>
              <p className="muted">No rules yet. Add one above.</p>
            </div>
          )}
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {myEffects.rules.map((rule: any, idx: number) => (
              <div key={idx} style={{
                display: "flex", alignItems: "center", gap: 12, padding: "10px 14px",
                background: "var(--bg-elevated)", border: "1px solid var(--border)",
                borderRadius: "var(--radius-sm)", transition: "border-color 0.15s",
              }}>
                <span style={{ flex: 1, fontSize: 14, lineHeight: 1.5, direction: "auto" as any }}>{rule.text}</span>
                <span style={{
                  flexShrink: 0, fontSize: 10, fontWeight: 700, textTransform: "uppercase" as any,
                  letterSpacing: "0.05em", padding: "3px 8px", borderRadius: 4,
                  background: rule.priority === "hard" ? "var(--error-soft)" : "var(--success-soft)",
                  color: rule.priority === "hard" ? "var(--error)" : "var(--success)",
                }}>{rule.priority}</span>
                <button className="danger-sm" onClick={() => handleRemoveRule(idx)} aria-label="Remove rule">&#10005;</button>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
