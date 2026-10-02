import React from "react";
import { api, type EffectPreset, type RafieiStyle } from "./api";

const ENERGY_COLORS: Record<number, string> = {
  5: "#ef4444", 4: "#f97316", 3: "#eab308", 2: "#22c55e", 1: "#3b82f6",
};
const hintColor = (effect: EffectPreset) => effect.hint_color || ENERGY_COLORS[effect.energy ?? 3] || "#94a3b8";

export default function MyEffects() {
  const [effects, setEffects] = React.useState<EffectPreset[]>([]);
  const [myEffects, setMyEffects] = React.useState<any>(null);
  const [rafiei, setRafiei] = React.useState<RafieiStyle | null>(null);
  const [applyingRafiei, setApplyingRafiei] = React.useState(false);
  const [error, setError] = React.useState("");
  const [newRule, setNewRule] = React.useState("");
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    Promise.all([
      api.listEffects().then(setEffects),
      fetch("/api/my-effects")
        .then(r => {
          if (!r.ok) throw new Error(`Failed to load My Effects: ${r.status}`);
          return r.json();
        })
        .then(setMyEffects),
      api.getRafieiStyles().then(setRafiei),
    ]).catch(e => setError(String(e))).finally(() => setLoading(false));
  }, []);

  async function handleApplyRafiei() {
    setApplyingRafiei(true); setError("");
    try {
      await api.applyRafieiStyle();
      const response = await fetch("/api/my-effects");
      if (!response.ok) throw new Error("Could not reload My Effects");
      setMyEffects(await response.json());
    } catch (e) { setError(String(e)); }
    finally { setApplyingRafiei(false); }
  }

  const handleAddRule = () => {
    if (newRule.trim() && myEffects) {
      const updated = {
        ...myEffects,
        rules: [...myEffects.rules, { text: newRule, priority: "hard" }],
      };
      fetch("/api/my-effects", {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(updated),
      })
        .then(r => {
          if (!r.ok) throw new Error(`Failed to save rule: ${r.status}`);
          return r.json();
        })
        .then(() => {
          setMyEffects(updated);
          setNewRule("");
        })
        .catch(e => setError(String(e)));
    }
  };

  const handleRemoveRule = (index: number) => {
    if (myEffects) {
      const updated = {
        ...myEffects,
        rules: myEffects.rules.filter((_: any, i: number) => i !== index),
      };
      fetch("/api/my-effects", {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(updated),
      })
        .then(r => {
          if (!r.ok) throw new Error(`Failed to remove rule: ${r.status}`);
          return r.json();
        })
        .then(() => setMyEffects(updated))
        .catch(e => setError(String(e)));
    }
  };

  const handleToggleFavorite = (effectId: string) => {
    if (myEffects) {
      const updated = { ...myEffects, favorites: { ...myEffects.favorites } };
      if (updated.favorites[effectId]) {
        delete updated.favorites[effectId];
      } else {
        updated.favorites[effectId] = { weight: 1.0, tags: [] };
      }
      fetch("/api/my-effects", {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(updated),
      })
        .then(r => {
          if (!r.ok) throw new Error(`Failed to save favorite: ${r.status}`);
          return r.json();
        })
        .then(() => setMyEffects(updated))
        .catch(e => setError(String(e)));
    }
  };

  if (loading) return <div>Loading...</div>;
  if (!myEffects) return <div>{error || "Error loading My Effects"}</div>;

  const rafieiSelected = !!rafiei &&
    rafiei.preferred_effects.every(id => myEffects.favorites[id]?.tags?.includes("rafiei")) &&
    rafiei.avoid_effects.every(id => myEffects.dislikes.includes(id));
  const noZoomRule = myEffects.rules.some((rule: { text?: string }) =>
    /زوم نکن|بدون زوم|no zoom|don't zoom/i.test(rule.text || ""));

  return (
    <div className="my-effects">
      <h1>My Effects</h1>
      {error && <p role="alert">{error}</p>}

      {rafiei && <section className={`rafiei-style-section ${rafieiSelected ? "selected" : ""}`}>
        <div className="section-heading">
          <h2>🎬 Rafiei Style</h2>
          {rafieiSelected && <span className="selected-badge" role="status">Selected ✓</span>}
          <button type="button" onClick={handleApplyRafiei} disabled={applyingRafiei}
            aria-pressed={rafieiSelected}>
            {applyingRafiei ? "Selecting…" : rafieiSelected ? "Reapply Rafiei Style" : "Select Rafiei Style"}
          </button>
        </div>
        <p className="muted">Select this preset to add its five preferred effects and avoid shake and glitch effects. You can also select it by clicking any preview card.</p>
        {rafieiSelected && noZoomRule && <p className="preset-warning" role="note">
          Your existing no-zoom rule is still active and can prevent Rafiei punch-ins. Edit it under My Rules if you want those shots.
        </p>}
        <div className="effect-grid">
          {rafiei.preferred_effects.map(id => {
            const eff = effects.find(item => item.id === id);
            return eff && <button key={id} type="button" className="effect-card rafiei-preferred"
              onClick={handleApplyRafiei} disabled={applyingRafiei}
              aria-label={`Select Rafiei Style: ${eff.label}`}
              aria-pressed={rafieiSelected}
              style={{ borderLeftColor: hintColor(eff) }} title={eff.description}>
              <div className="effect-label">{eff.label}</div>
              <span className="mood-badge" style={{ color: hintColor(eff) }}>{eff.mood}</span>
              <div className="effect-desc">{eff.description}</div>
            </button>;
          })}
        </div>
        <p className="muted">Avoid: {rafiei.avoid_effects.join(", ")}</p>
      </section>}

      <section>
        <h2>Favorites</h2>
        <div className="effect-grid">
          {effects.map(eff => (
            <div
              key={eff.id}
              className={`effect-card ${
                myEffects.favorites[eff.id] ? "favorite" : ""
              }`}
              style={{ borderLeftColor: hintColor(eff) }}
              title={`${eff.description}${eff.best_roles?.length ? `\nBest for: ${eff.best_roles.join(", ")}` : ""}`}
              onClick={() => handleToggleFavorite(eff.id)}
            >
              <div className="effect-label">{eff.label}</div>
              <span className="mood-badge" style={{ color: hintColor(eff) }}>{eff.mood}</span>
              <div className="effect-desc">{eff.description}</div>
              <div className="effect-star">
                {myEffects.favorites[eff.id] ? "★" : "☆"}
              </div>
              {myEffects.favorites[eff.id] && (
                <input
                  type="range"
                  min="0.5"
                  max="2"
                  step="0.1"
                  defaultValue={
                    myEffects.favorites[eff.id].weight || 1.0
                  }
                  onClick={e => e.stopPropagation()}
                  onChange={e => {
                    const fav = {
                      ...myEffects.favorites[eff.id],
                      weight: parseFloat(e.target.value),
                    };
                    const updated = {
                      ...myEffects,
                      favorites: {
                        ...myEffects.favorites,
                        [eff.id]: fav,
                      },
                    };
                    fetch("/api/my-effects", {
                      method: "PUT",
                      headers: { "content-type": "application/json" },
                      body: JSON.stringify(updated),
                    })
                      .then(r => {
                        if (!r.ok) throw new Error(`Failed to save weight: ${r.status}`);
                        return r.json();
                      })
                      .then(() => setMyEffects(updated))
                      .catch(e => setError(String(e)));
                  }}
                />
              )}
            </div>
          ))}
        </div>
      </section>

      <section>
        <h2>My Rules</h2>
        <div className="rules-editor">
          <div className="rule-input">
            <input
              type="text"
              placeholder="Add rule in Persian or English... (e.g., 'روی اعداد زوم سریع')"
              value={newRule}
              onChange={e => setNewRule(e.target.value)}
              onKeyDown={e => {
                if (e.key === "Enter") handleAddRule();
              }}
            />
            <button onClick={handleAddRule}>Add</button>
          </div>
          <ul className="rules-list">
            {myEffects.rules.map((rule: any, idx: number) => (
              <li key={idx}>
                <span>{rule.text}</span>
                <span className="priority">{rule.priority}</span>
                <button
                  className="delete"
                  onClick={() => handleRemoveRule(idx)}
                >
                  ✕
                </button>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <style>{`
        .my-effects {
          padding: 2rem;
          max-width: 1200px;
          margin: 0 auto;
        }
        h1 {
          font-size: 2rem;
          margin-bottom: 1.5rem;
        }
        h2 {
          font-size: 1.3rem;
          margin-top: 2rem;
          margin-bottom: 1rem;
        }
        section {
          margin-bottom: 3rem;
        }
        .effect-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
          gap: 1rem;
        }
        .effect-card {
          border: 2px solid #334155;
          border-left-width: 5px;
          border-radius: 8px;
          padding: 0.8rem;
          cursor: pointer;
          text-align: left;
          transition: all 0.2s;
          position: relative;
        }
        .effect-card:hover {
          background: #1e293b;
        }
        .effect-card.favorite {
          border-top-color: #ffd700;
          background: #1e1a00;
        }
        .rafiei-style-section { border: 2px solid #334155; border-radius: 12px; padding: 18px; }
        .rafiei-style-section.selected { border-color: #22c55e; }
        .selected-badge { color: #86efac; background: #14532d; border-radius: 99px; padding: 4px 10px; font-size: 0.8rem; font-weight: 700; }
        .preset-warning { color: #fde68a; background: #713f1233; border-left: 3px solid #f59e0b; padding: 8px 10px; font-size: 0.8rem; }
        .effect-card.rafiei-preferred { border-top-color: #2563eb; background: #0f172a; color: var(--text); width: 100%; font-family: inherit; }
        .effect-card.rafiei-preferred:focus-visible { outline: 3px solid #4f8cff; outline-offset: 2px; }
        .section-heading { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
        .section-heading h2 { margin: 0; }
        .mood-badge { display: inline-block; border-radius: 99px; padding: 2px 7px; font-size: 0.7rem; font-weight: 600; background: #ffffff18; }
        .effect-desc { font-size: 0.75rem; color: #94a3b8; margin-top: 6px; line-height: 1.4; }
        .effect-label {
          font-weight: 500;
          font-size: 0.9rem;
          word-break: break-word;
        }
        .effect-star {
          font-size: 1.5rem;
          margin: 0.5rem 0;
        }
        input[type="range"] {
          width: 100%;
          cursor: pointer;
        }
        .rules-editor {
          background: #f9f9f9;
          border: 1px solid #ddd;
          border-radius: 8px;
          padding: 1rem;
        }
        .rule-input {
          display: flex;
          gap: 0.5rem;
          margin-bottom: 1rem;
        }
        .rule-input input {
          flex: 1;
          padding: 0.5rem;
          border: 1px solid #ccc;
          border-radius: 4px;
          font-size: 1rem;
        }
        .rule-input button {
          padding: 0.5rem 1rem;
          background: #007bff;
          color: white;
          border: none;
          border-radius: 4px;
          cursor: pointer;
        }
        .rule-input button:hover {
          background: #0056b3;
        }
        .rules-list {
          list-style: none;
          padding: 0;
        }
        .rules-list li {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 0.75rem;
          background: white;
          border: 1px solid #eee;
          border-radius: 4px;
          margin-bottom: 0.5rem;
        }
        .priority {
          font-size: 0.75rem;
          padding: 0.25rem 0.5rem;
          background: #e7f3ff;
          border-radius: 3px;
          margin-left: 0.5rem;
        }
        .delete {
          background: none;
          border: none;
          color: #999;
          cursor: pointer;
          font-size: 1rem;
          padding: 0;
          margin-left: 0.5rem;
        }
        .delete:hover {
          color: #d32f2f;
        }
      `}</style>
    </div>
  );
}
