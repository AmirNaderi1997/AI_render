import React from "react";
import { api } from "./api";

interface Effect {
  id: string;
  motion: string;
  light: string;
  label: string;
  description: string;
}

export default function MyEffects() {
  const [effects, setEffects] = React.useState<Effect[]>([]);
  const [myEffects, setMyEffects] = React.useState<any>(null);
  const [editMode, setEditMode] = React.useState(false);
  const [newRule, setNewRule] = React.useState("");
  const [newFavorite, setNewFavorite] = React.useState("");
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    Promise.all([
      api.listEffects().then(setEffects),
      fetch("/api/my-effects").then(r => r.json()).then(setMyEffects),
    ]).finally(() => setLoading(false));
  }, []);

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
        .then(r => r.json())
        .then(() => {
          setMyEffects(updated);
          setNewRule("");
        });
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
        .then(r => r.json())
        .then(() => setMyEffects(updated));
    }
  };

  const handleToggleFavorite = (effectId: string) => {
    if (myEffects) {
      const updated = { ...myEffects };
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
        .then(r => r.json())
        .then(() => setMyEffects(updated));
    }
  };

  if (loading) return <div>Loading...</div>;
  if (!myEffects) return <div>Error loading My Effects</div>;

  return (
    <div className="my-effects">
      <h1>My Effects</h1>

      <section>
        <h2>Favorites</h2>
        <div className="effect-grid">
          {effects.map(eff => (
            <div
              key={eff.id}
              className={`effect-card ${
                myEffects.favorites[eff.id] ? "favorite" : ""
              }`}
              onClick={() => handleToggleFavorite(eff.id)}
            >
              <div className="effect-label">{eff.label}</div>
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
                      .then(r => r.json())
                      .then(() => setMyEffects(updated));
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
          grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
          gap: 1rem;
        }
        .effect-card {
          border: 2px solid #ccc;
          border-radius: 8px;
          padding: 1rem;
          cursor: pointer;
          text-align: center;
          transition: all 0.2s;
          position: relative;
        }
        .effect-card:hover {
          border-color: #999;
          background: #f5f5f5;
        }
        .effect-card.favorite {
          border-color: #ffd700;
          background: #fffacd;
        }
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
