import { useState, useEffect, useRef, useCallback } from "react";

// ─── Config ────────────────────────────────────────────────────────────────
// Replace with your deployed Railway/Render URL, e.g.:
// const WS_BASE = "wss://spender-production.up.railway.app/ws";
const WS_BASE = import.meta.env.VITE_WS_URL || "ws://localhost:8000/ws";

// ─── Constants ─────────────────────────────────────────────────────────────
const GEM_COLORS = ["white", "blue", "green", "red", "black"];
const GEM_LABELS = { white:"Diamond", blue:"Sapphire", green:"Emerald", red:"Ruby", black:"Onyx", gold:"Gold" };
const GEM_HEX    = { white:"#e8e0d0", blue:"#4a9eff", green:"#3dba6e", red:"#e05555", black:"#4a4a5a", gold:"#f5c842" };

// ─── Helpers ───────────────────────────────────────────────────────────────
function uid() { return Math.random().toString(36).slice(2, 10); }
function emptyGems() { return { white:0, blue:0, green:0, red:0, black:0, gold:0 }; }
function gemTotal(tokens) { return Object.values(tokens).reduce((a,b) => a+b, 0); }

function bonusesFrom(purchased) {
	const b = emptyGems();
	for (const c of purchased) b[c.bonus] = (b[c.bonus] || 0) + 1;
	return b;
}
function canAfford(cost, tokens, bonuses) {
	let gold = 0;
	for (const c of GEM_COLORS) {
		const need = Math.max(0, (cost[c]||0) - (bonuses[c]||0));
		const have = tokens[c]||0;
		if (have < need) gold += need - have;
	}
	return gold <= (tokens.gold||0);
}
function totalPoints(purchased, nobles) {
	return purchased.reduce((s,c) => s+c.points, 0) + nobles.reduce((s,n) => s+n.points, 0);
}

// ─── Styles ────────────────────────────────────────────────────────────────
const css = `
@import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@400;600;700&family=Crimson+Pro:ital,wght@0,300;0,400;1,300&display=swap');
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
	--bg:#0f0e0c;--surface:#1a1814;--surface2:#242018;--border:#3a342a;
	--gold:#c9a84c;--gold-light:#e8c96a;--text:#e8dfc8;--text-dim:#8a7d6a;
	--white-gem:#ddd4be;--blue-gem:#4a9eff;--green-gem:#3dba6e;
	--red-gem:#e05555;--black-gem:#6a6a7a;--gold-gem:#f5c842;
	--radius:8px;--radius-lg:14px;
}
body{background:var(--bg);color:var(--text);font-family:'Crimson Pro',Georgia,serif;min-height:100vh}
.app{min-height:100vh;display:flex;flex-direction:column}

/* Lobby */
.lobby{max-width:480px;margin:0 auto;padding:60px 24px;text-align:center}
.lobby h1{font-family:'Cinzel',serif;font-size:3rem;font-weight:700;color:var(--gold);letter-spacing:.06em;margin-bottom:8px}
.tagline{color:var(--text-dim);font-style:italic;font-size:1.1rem;margin-bottom:48px}
.lobby-card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:28px;margin-bottom:16px;text-align:left}
.lobby-card h2{font-family:'Cinzel',serif;font-size:1rem;color:var(--gold);margin-bottom:16px;letter-spacing:.08em}
.room-id-display{font-family:'Cinzel',serif;font-size:2rem;letter-spacing:.25em;color:var(--gold-light);text-align:center;padding:16px;background:var(--surface2);border-radius:var(--radius);margin:8px 0 16px;border:1px solid var(--border)}
.input{width:100%;padding:10px 14px;background:var(--surface2);border:1px solid var(--border);border-radius:var(--radius);color:var(--text);font-family:'Cinzel',serif;font-size:1rem;letter-spacing:.1em;outline:none}
.input:focus{border-color:var(--gold)}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;padding:10px 22px;border-radius:var(--radius);border:none;cursor:pointer;font-family:'Cinzel',serif;font-size:.85rem;letter-spacing:.06em;font-weight:600;transition:all .15s}
.btn-gold{background:var(--gold);color:#0f0e0c}.btn-gold:hover{background:var(--gold-light)}
.btn-outline{background:transparent;color:var(--gold);border:1px solid var(--gold)}.btn-outline:hover{background:var(--gold);color:#0f0e0c}
.btn-ghost{background:transparent;color:var(--text-dim);border:1px solid var(--border)}.btn-ghost:hover{border-color:var(--text-dim);color:var(--text)}
.btn:disabled{opacity:.4;cursor:not-allowed}
.btn-full{width:100%}
.gap-8{display:flex;gap:8px}
.mt-8{margin-top:8px}
.status-msg{font-size:.9rem;color:var(--text-dim);font-style:italic;text-align:center;padding:8px 0}
.error-msg{font-size:.9rem;color:var(--red-gem);text-align:center;padding:8px 0}

/* Waiting */
.waiting{text-align:center}
.waiting h2{font-family:'Cinzel',serif;color:var(--gold);margin-bottom:8px}
.player-list{list-style:none;margin:16px 0}
.player-list li{padding:8px 12px;background:var(--surface2);border-radius:var(--radius);margin-bottom:6px;font-family:'Cinzel',serif;font-size:.85rem;letter-spacing:.05em}
.player-list li.me{border:1px solid var(--gold);color:var(--gold)}

/* Game */
.game{display:grid;grid-template-columns:1fr 280px;gap:12px;padding:12px;min-height:100vh}
@media(max-width:900px){.game{grid-template-columns:1fr}}
.game-main{grid-column:1;display:flex;flex-direction:column;gap:10px}
.game-sidebar{grid-column:2;display:flex;flex-direction:column;gap:10px}
@media(max-width:900px){.game-sidebar{grid-column:1}}
.panel{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:14px}
.panel-title{font-family:'Cinzel',serif;font-size:.7rem;letter-spacing:.12em;color:var(--gold);margin-bottom:10px;text-transform:uppercase}

/* Bank */
.bank-gems{display:flex;gap:8px;flex-wrap:wrap}
.gem-stack{display:flex;flex-direction:column;align-items:center;gap:4px;cursor:pointer;transition:transform .12s}
.gem-stack:hover .gem-token{transform:scale(1.08)}
.gem-stack.selected .gem-token{box-shadow:0 0 0 2px var(--gold-light)}
.gem-stack.disabled{opacity:.35;cursor:not-allowed}
.gem-token{width:42px;height:42px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-family:'Cinzel',serif;font-weight:700;font-size:.95rem;border:2px solid rgba(255,255,255,.15);transition:all .12s}
.gem-count{font-size:.75rem;color:var(--text-dim);font-family:'Cinzel',serif}

/* Cards */
.level-row{display:flex;gap:8px;align-items:flex-start;flex-wrap:wrap}
.deck-pile{width:72px;min-height:100px;border-radius:var(--radius);border:1px dashed var(--border);display:flex;align-items:center;justify-content:center;font-family:'Cinzel',serif;font-size:.7rem;color:var(--text-dim);cursor:pointer;flex-shrink:0;background:var(--surface2);transition:border-color .12s;flex-direction:column;gap:4px}
.deck-pile:hover{border-color:var(--gold);color:var(--gold)}
.deck-pile.disabled{cursor:not-allowed}
.deck-remaining{font-size:1.2rem;font-weight:700;color:var(--text);font-family:'Cinzel',serif}
.card{width:88px;min-height:120px;border-radius:var(--radius);background:var(--surface2);border:1px solid var(--border);padding:8px 6px 6px;display:flex;flex-direction:column;cursor:pointer;transition:all .15s;flex-shrink:0}
.card:hover{border-color:var(--gold);transform:translateY(-2px);box-shadow:0 6px 20px rgba(0,0,0,.4)}
.card.selected{border-color:var(--gold-light);box-shadow:0 0 0 2px var(--gold-light)}
.card.affordable{border-color:var(--green-gem)}
.card.disabled{cursor:not-allowed;opacity:.6}
.card-header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6px}
.card-points{font-family:'Cinzel',serif;font-weight:700;font-size:1.1rem;color:var(--gold);min-width:16px}
.card-points.zero{color:transparent}
.card-bonus{width:20px;height:20px;border-radius:50%;flex-shrink:0}
.card-cost{display:flex;flex-direction:column;gap:3px;margin-top:auto}
.cost-row{display:flex;align-items:center;gap:4px}
.cost-gem{width:10px;height:10px;border-radius:50%;flex-shrink:0}
.cost-num{font-family:'Cinzel',serif;font-size:.7rem;color:var(--text-dim)}

/* Nobles */
.nobles-row{display:flex;gap:8px;flex-wrap:wrap}
.noble{width:72px;min-height:72px;border-radius:var(--radius);background:var(--surface2);border:1px solid var(--border);padding:6px;display:flex;flex-direction:column;align-items:center;gap:4px}
.noble-points{font-family:'Cinzel',serif;font-size:1rem;font-weight:700;color:var(--gold)}
.noble-req{display:flex;flex-direction:column;gap:2px;width:100%}
.noble-req-row{display:flex;gap:3px;align-items:center;font-size:.65rem;color:var(--text-dim);font-family:'Cinzel',serif}

/* Action bar */
.action-bar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:10px 14px;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg)}
.action-hint{flex:1;font-style:italic;color:var(--text-dim);font-size:.9rem}
.turn-badge{font-family:'Cinzel',serif;font-size:.75rem;letter-spacing:.08em;padding:4px 10px;border-radius:20px}
.turn-badge.mine{background:var(--gold);color:#0f0e0c}
.turn-badge.theirs{background:var(--surface2);color:var(--text-dim);border:1px solid var(--border)}

/* Player panels */
.players-area{display:flex;flex-direction:column;gap:8px}
.player-panel{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:12px;transition:border-color .2s}
.player-panel.active-turn{border-color:var(--gold)}
.player-panel.me{border-left:3px solid var(--gold)}
.player-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
.player-name{font-family:'Cinzel',serif;font-size:.8rem;letter-spacing:.06em}
.player-score{font-family:'Cinzel',serif;font-size:1.1rem;font-weight:700;color:var(--gold)}
.player-tokens{display:flex;gap:5px;flex-wrap:wrap;margin-bottom:6px}
.token-pill{display:flex;align-items:center;gap:3px;padding:2px 7px;border-radius:12px;font-family:'Cinzel',serif;font-size:.7rem;font-weight:700}
.player-bonuses{display:flex;gap:5px;flex-wrap:wrap;margin-bottom:6px}
.bonus-pill{display:flex;align-items:center;gap:3px;padding:2px 7px;border-radius:12px;font-family:'Cinzel',serif;font-size:.7rem;font-weight:700;border:1px solid}
.reserved-label{font-size:.65rem;color:var(--text-dim);font-family:'Cinzel',serif;letter-spacing:.06em;margin-bottom:4px}
.reserved-row{display:flex;gap:4px;flex-wrap:wrap}

/* Winner */
.winner-screen{display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:100vh;text-align:center;padding:32px}
.winner-title{font-family:'Cinzel',serif;font-size:3rem;color:var(--gold);margin-bottom:8px}
.winner-sub{color:var(--text-dim);font-style:italic;margin-bottom:32px}
.final-scores{display:flex;flex-direction:column;gap:8px;margin-bottom:32px}
.score-row{font-family:'Cinzel',serif;font-size:1.1rem;padding:8px 24px;background:var(--surface);border-radius:var(--radius)}
.score-row.winner{border:1px solid var(--gold);color:var(--gold)}

/* Toast */
.toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:var(--surface);border:1px solid var(--gold);padding:10px 20px;border-radius:var(--radius);font-family:'Cinzel',serif;font-size:.8rem;color:var(--gold);z-index:999;pointer-events:none;animation:fadeup .3s ease}
@keyframes fadeup{from{opacity:0;transform:translateX(-50%) translateY(10px)}to{opacity:1;transform:translateX(-50%) translateY(0)}}

/* Discard modal */
.modal-backdrop{position:fixed;inset:0;background:rgba(0,0,0,.75);display:flex;align-items:center;justify-content:center;z-index:100}
.modal{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:24px;max-width:400px;width:90%}
.modal h3{font-family:'Cinzel',serif;color:var(--gold);margin-bottom:8px}
.modal p{color:var(--text-dim);font-size:.9rem;margin-bottom:16px}
.discard-gems{display:flex;gap:8px;flex-wrap:wrap;justify-content:center;margin-bottom:16px}
.discard-btn{padding:6px 14px;border-radius:var(--radius);border:1px solid var(--border);background:var(--surface2);color:var(--text);cursor:pointer;font-family:'Cinzel',serif;font-size:.8rem;transition:all .12s}
.discard-btn:hover{border-color:var(--gold);color:var(--gold)}
.discard-count{text-align:center;font-family:'Cinzel',serif;color:var(--text-dim);font-size:.85rem}
.conn-dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:6px}
.conn-dot.connected{background:var(--green-gem)}
.conn-dot.disconnected{background:var(--red-gem)}
`;

// ─── Sub-components ───────────────────────────────────────────────────────

function GemToken({ color, size = 42 }) {
	return (
		<div className="gem-token" style={{
			background: GEM_HEX[color], width: size, height: size,
			color: color === "white" || color === "gold" ? "#333" : "#fff",
		}}>
			{color === "gold" ? "★" : color[0].toUpperCase()}
		</div>
	);
}

function CardView({ card, selected, affordable, disabled, onClick, compact }) {
	return (
		<div
			className={`card${selected?" selected":""}${affordable?" affordable":""}${disabled?" disabled":""}`}
			style={{ width: compact ? 72 : 88, minHeight: compact ? 96 : 120 }}
			onClick={disabled ? undefined : onClick}
		>
			<div className="card-header">
				<span className={`card-points${card.points===0?" zero":""}`}>{card.points||""}</span>
				<div className="card-bonus" style={{ background: GEM_HEX[card.bonus] }} />
			</div>
			<div className="card-cost">
				{Object.entries(card.cost).map(([c,n]) => n>0 && (
					<div key={c} className="cost-row">
						<div className="cost-gem" style={{ background: GEM_HEX[c] }} />
						<span className="cost-num">{n}</span>
					</div>
				))}
			</div>
		</div>
	);
}

function NobleView({ noble }) {
	return (
		<div className="noble">
			<span className="noble-points">{noble.points}</span>
			<div className="noble-req">
				{Object.entries(noble.req).map(([c,n]) => (
					<div key={c} className="noble-req-row">
						<div style={{width:8,height:8,borderRadius:"50%",background:GEM_HEX[c]}}/>
						<span>{n}</span>
					</div>
				))}
			</div>
		</div>
	);
}

// ─── useWebSocket hook ─────────────────────────────────────────────────────

function useWebSocket(onMessage) {
	const wsRef = useRef(null);
	const [connected, setConnected] = useState(false);
	const onMsgRef = useRef(onMessage);
	onMsgRef.current = onMessage;

	const connect = useCallback((url) => {
		if (wsRef.current) wsRef.current.close();
		const ws = new WebSocket(url);
		wsRef.current = ws;
		ws.onopen = () => setConnected(true);
		ws.onclose = () => setConnected(false);
		ws.onerror = () => setConnected(false);
		ws.onmessage = (e) => {
			try { onMsgRef.current(JSON.parse(e.data)); } catch {}
		};
	}, []);

	const send = useCallback((data) => {
		if (wsRef.current?.readyState === WebSocket.OPEN) {
			wsRef.current.send(JSON.stringify(data));
		}
	}, []);

	const disconnect = useCallback(() => {
		wsRef.current?.close();
		wsRef.current = null;
	}, []);

	return { connected, connect, send, disconnect };
}

// ─── Main App ──────────────────────────────────────────────────────────────

export default function SpenderApp() {
	const [myId] = useState(() => uid());
	const [myName, setMyName] = useState("");
	const [screen, setScreen] = useState("lobby");
	const [roomId, setRoomId] = useState("");
	const [joinInput, setJoinInput] = useState("");
	const [roomData, setRoomData] = useState(null);
	const [error, setError] = useState("");
	const [toast, setToast] = useState("");
	const [needsDiscard, setNeedsDiscard] = useState(false);

	// game interaction state
	const [selectedGems, setSelectedGems] = useState([]);
	const [selectedCard, setSelectedCard] = useState(null);

	const handleMessage = useCallback((msg) => {
		if (msg.type === "created") {
			setRoomId(msg.room_id);
			setRoomData(msg.room);
			setScreen("waiting");
		} else if (msg.type === "room_update") {
			setRoomData(msg.room);
			if (msg.room.status === "playing" && screen !== "game") setScreen("game");
			if (msg.room.game?.phase === "over") setScreen("game");
			if (msg.needs_discard === myId) setNeedsDiscard(true);
			else setNeedsDiscard(false);
		} else if (msg.type === "error") {
			setToast(msg.message);
		}
	}, [myId, screen]);

	const { connected, connect, send, disconnect } = useWebSocket(handleMessage);

	// Connect WebSocket on mount
	useEffect(() => {
			// attempt reconnect with saved token for any room if present
			try{
				const tok = localStorage.getItem('spender_token_' + myId);
				if(tok){
					// connect and send reconnect with token
					connect(`${WS_BASE}/${myId}`);
					setTimeout(() => send({ action: 'reconnect', token: tok }), 300);
				}else{
					connect(`${WS_BASE}/${myId}`);
				}
			}catch(e){ connect(`${WS_BASE}/${myId}`); }
		return () => disconnect();
	}, [connect, disconnect, myId]);

	useEffect(() => {
		if (toast) { const t = setTimeout(() => setToast(""), 2500); return () => clearTimeout(t); }
	}, [toast]);

	const game = roomData?.game;
	const me = game?.players?.[myId];
	const myTurn = game?.turn === myId;
	const myBonuses = me ? bonusesFrom(me.purchased) : emptyGems();

	// ── Actions ────────────────────────────────────────────────────────────

	const handleCreate = () => {
		if (!myName.trim()) { setError("Enter your name first"); return; }
		setError("");
		send({ action: "create", name: myName.trim() });
	};

	const handleJoin = () => {
		if (!myName.trim()) { setError("Enter your name first"); return; }
		const id = joinInput.trim().toUpperCase();
		if (!id) { setError("Enter a room code"); return; }
		setError("");
		setRoomId(id);
		connect(`${WS_BASE}/${myId}`);
		// slight delay to let WS open before sending join
		setTimeout(() => send({ action: "join", room_id: id, name: myName.trim() }), 300);
	};

	const handleStart = () => {
		send({ action: "start", room_id: roomId });
	};

	const sendMove = (move) => {
		send({ action: "move", room_id: roomId, move });
	};

	const handleTakeGems = () => {
		if (!myTurn || selectedGems.length === 0) return;
		sendMove({ type: "take_gems", colors: selectedGems });
		setSelectedGems([]);
	};

	const handleReserve = (card, deckLevel) => {
		if (!myTurn) return;
		if (deckLevel) {
			sendMove({ type: "reserve", deck_level: deckLevel });
		} else {
			sendMove({ type: "reserve", card_id: card.id });
		}
		setSelectedCard(null);
	};

	const handleBuy = (card) => {
		if (!myTurn) return;
		sendMove({ type: "buy", card_id: card.id });
		setSelectedCard(null);
	};

	const handleDiscard = (color) => {
		sendMove({ type: "discard", color });
	};

	// ── Gem selection ──────────────────────────────────────────────────────
	const handleGemClick = (color) => {
		if (!myTurn) return;
		if ((game?.bank[color] || 0) <= 0) return;
		setSelectedGems(prev => {
			const freq = {};
			for (const c of prev) freq[c] = (freq[c]||0)+1;
			if (prev.includes(color)) {
				const idx = prev.lastIndexOf(color);
				return [...prev.slice(0,idx),...prev.slice(idx+1)];
			}
			if (prev.length >= 3) return prev;
			if (freq[color] === 1) {
				if (Object.keys(freq).length === 1) return [...prev, color];
				return prev;
			}
			if (Object.keys(freq).length < 3) return [...prev, color];
			return prev;
		});
	};

	// ── Render helpers ─────────────────────────────────────────────────────
	function renderCard(card, opts={}) {
		if (!card) return <div key={Math.random()} style={{width:88,minHeight:120}}/>;
		const affordable = me && canAfford(card.cost, me.tokens, myBonuses);
		const isSelected = selectedCard?.card?.id === card.id;
		return (
			<CardView key={card.id} card={card}
				selected={isSelected}
				affordable={affordable && myTurn}
				disabled={opts.disabled}
				onClick={() => {
					if (!myTurn) return;
					setSelectedCard(isSelected ? null : { card, source: opts.source||"board" });
				}}
			/>
		);
	}

	function renderPlayerPanel(pid) {
		const p = game?.players?.[pid];
		if (!p) return null;
		const name = roomData?.players?.[pid] || pid.slice(0,6);
		const bonuses = bonusesFrom(p.purchased);
		const score = totalPoints(p.purchased, p.nobles);
		const isMe = pid === myId;
		const isActive = game?.turn === pid;
		return (
			<div key={pid} className={`player-panel${isMe?" me":""}${isActive?" active-turn":""}`}>
				<div className="player-header">
					<span className="player-name">{name}{isMe?" (you)":""}{isActive?" ●":""}</span>
					<span className="player-score">{score} pts</span>
				</div>
				<div className="player-tokens">
					{[...GEM_COLORS,"gold"].map(c => (p.tokens[c]||0)>0 && (
						<span key={c} className="token-pill" style={{background:GEM_HEX[c]+"33",border:`1px solid ${GEM_HEX[c]}`}}>
							<span style={{width:8,height:8,borderRadius:"50%",background:GEM_HEX[c],display:"inline-block"}}/>
							{p.tokens[c]}
						</span>
					))}
				</div>
				<div className="player-bonuses">
					{GEM_COLORS.map(c => (bonuses[c]||0)>0 && (
						<span key={c} className="bonus-pill" style={{borderColor:GEM_HEX[c],color:GEM_HEX[c]}}>+{bonuses[c]} {c[0].toUpperCase()}</span>
					))}
					{p.nobles.map(n => (
						<span key={n.id} className="bonus-pill" style={{borderColor:"var(--gold)",color:"var(--gold)"}}>★{n.points}</span>
					))}
				</div>
				{isMe && p.reserved?.length>0 && (
					<>
						<div className="reserved-label">RESERVED ({p.reserved.length}/3)</div>
						<div className="reserved-row">{p.reserved.map(c => renderCard(c,{source:"reserved"}))}</div>
					</>
				)}
			</div>
		);
	}

	function getHint() {
		if (!myTurn) return `Waiting for ${roomData?.players?.[game?.turn]||"opponent"}…`;
		if (selectedCard) {
			const affordable = canAfford(selectedCard.card.cost, me?.tokens||emptyGems(), myBonuses);
			return affordable ? "Buy or reserve this card" : "Reserve this card (can't afford yet)";
		}
		if (selectedGems.length > 0) return `${selectedGems.length} gem(s) selected — confirm to take`;
		return "Select gems, or click a card to buy/reserve";
	}

	// ── Screens ────────────────────────────────────────────────────────────

	if (screen === "lobby") return (
		<>
			<style>{css}</style>
			<div className="app">
				<div className="lobby">
					<h1>Spender</h1>
					<p className="tagline">A gem merchant's game of prestige</p>
					<div className="lobby-card">
						<h2>YOUR NAME</h2>
						<input className="input" placeholder="Enter your name…" value={myName}
							onChange={e => setMyName(e.target.value)} maxLength={18}
							onKeyDown={e => e.key==="Enter" && handleCreate()}
						/>
					</div>
					<div className="lobby-card">
						<h2>CREATE ROOM</h2>
						<p style={{fontSize:".85rem",color:"var(--text-dim)",marginBottom:12,lineHeight:1.5}}>
							Start a new game and share the room code with your opponent.
						</p>
						<button className="btn btn-gold btn-full" onClick={handleCreate}>Create Room</button>
					</div>
					<div className="lobby-card">
						<h2>JOIN ROOM</h2>
						<input className="input" placeholder="ROOM CODE" value={joinInput}
							onChange={e => setJoinInput(e.target.value.toUpperCase())} maxLength={6}
							style={{marginBottom:8,textAlign:"center"}}
							onKeyDown={e => e.key==="Enter" && handleJoin()}
						/>
						<button className="btn btn-outline btn-full mt-8" onClick={handleJoin}>Join Room</button>
					</div>
					{error && <p className="error-msg">{error}</p>}
					<p className="status-msg">
						<span className={`conn-dot ${connected?"connected":"disconnected"}`}/>
						{connected ? "Connected to server" : "Connecting…"}
					</p>
				</div>
			</div>
		</>
	);

	if (screen === "waiting") return (
		<>
			<style>{css}</style>
			<div className="app">
				<div className="lobby">
					<div className="lobby-card waiting">
						<h2>Room {roomId}</h2>
						<p style={{color:"var(--text-dim)",fontSize:".85rem",marginBottom:12}}>Share this code:</p>
						<div className="room-id-display">{roomId}</div>
						<ul className="player-list">
							{roomData?.players && Object.entries(roomData.players).map(([id,name]) => (
								<li key={id} className={id===myId?"me":""}>{name}{id===myId?" (you)":""}</li>
							))}
						</ul>
						{roomData?.host === myId
							? <button className="btn btn-gold btn-full"
									disabled={!roomData?.players||Object.keys(roomData.players).length<2}
									onClick={handleStart}>Start Game</button>
							: <p className="status-msg">Waiting for host to start…</p>
						}
					</div>
				</div>
			</div>
		</>
	);

	if (screen === "game" && game?.phase === "over") {
		const winner = game.winner;
		const winnerName = roomData?.players?.[winner] || winner;
		return (
			<>
				<style>{css}</style>
				<div className="app">
					<div className="winner-screen">
						<div className="winner-title">Victory!</div>
						<p className="winner-sub">{winnerName} claims the gem trade</p>
						<div className="final-scores">
							{game.order.map(pid => {
								const score = totalPoints(game.players[pid].purchased, game.players[pid].nobles);
								const name = roomData?.players?.[pid]||pid.slice(0,6);
								return (
									<div key={pid} className={`score-row${pid===winner?" winner":""}`}>
										{pid===winner?"★ ":""}{name} — {score} pts
									</div>
								);
							})}
						</div>
						<button className="btn btn-outline" onClick={() => { setScreen("lobby"); setRoomData(null); setRoomId(""); }}>
							Back to Lobby
						</button>
					</div>
				</div>
			</>
		);
	}

	if (screen === "game" && game) return (
		<>
			<style>{css}</style>
			<div className="app">
				<div className="game">
					<div className="game-main">

						<div className="panel">
							<div className="panel-title">Nobles</div>
							<div className="nobles-row">{game.nobles.map(n => <NobleView key={n.id} noble={n}/>)}</div>
						</div>

						{[["L3","L2","L1"].map((lk,i) => (
							<div key={lk} className="panel">
								<div className="panel-title">Level {["III","II","I"][i]}</div>
								<div className="level-row">
									<div className={`deck-pile${!myTurn?" disabled":""}`}
										onClick={() => myTurn && handleReserve(null, 3-i)}
										title="Reserve blind from deck">
										<span style={{fontSize:".65rem",letterSpacing:".08em"}}>DECK</span>
										<span className="deck-remaining">{game.decks[lk]?.length||0}</span>
									</div>
									{game.board[lk].map((c,j) => c ? renderCard(c) : <div key={j} style={{width:88}}/>)}
								</div>
							</div>
						))]}

						<div className="panel">
							<div className="panel-title">Gem Bank</div>
							<div className="bank-gems">
								{[...GEM_COLORS,"gold"].map(c => {
									const count = game.bank[c]||0;
									const isGold = c==="gold";
									const isSel = selectedGems.filter(x=>x===c).length>0;
									return (
										<div key={c}
											className={`gem-stack${isSel?" selected":""}${!myTurn||isGold||count===0?" disabled":""}`}
											onClick={() => !isGold && handleGemClick(c)}
											title={GEM_LABELS[c]}>
											<GemToken color={c}/>
											<span className="gem-count">{count}</span>
										</div>
									);
								})}
							</div>
						</div>

						<div className="action-bar">
							<span className={`turn-badge ${myTurn?"mine":"theirs"}`}>
								{myTurn ? "Your Turn" : `${roomData?.players?.[game.turn]}'s Turn`}
							</span>
							<span className="action-hint">{getHint()}</span>
							{myTurn && selectedGems.length>0 && (
								<button className="btn btn-gold" onClick={handleTakeGems}>
									Take {selectedGems.length} Gem{selectedGems.length>1?"s":""}
								</button>
							)}
							{myTurn && selectedCard && (() => {
								const affordable = canAfford(selectedCard.card.cost, me?.tokens||emptyGems(), myBonuses);
								return (
									<div className="gap-8">
										{affordable && <button className="btn btn-gold" onClick={() => handleBuy(selectedCard.card)}>Buy Card</button>}
										{selectedCard.source!="reserved" && me?.reserved?.length<3 && (
											<button className="btn btn-outline" onClick={() => handleReserve(selectedCard.card)}>Reserve</button>
										)}
										<button className="btn btn-ghost" onClick={() => setSelectedCard(null)}>Cancel</button>
									</div>
								);
							})()}
						</div>
					</div>

					<div className="game-sidebar">
						<div className="panel-title" style={{padding:"0 4px"}}>Players</div>
						<div className="players-area">{game.order.map(pid => renderPlayerPanel(pid))}</div>
					</div>
				</div>

				{needsDiscard && me && (
					<div className="modal-backdrop">
						<div className="modal">
							<h3>Too Many Gems</h3>
							<p>Discard down to 10 gems total.</p>
							<div className="discard-gems">
								{[...GEM_COLORS,"gold"].map(c => {
									const count = me.tokens[c]||0;
									return count>0 && (
										<button key={c} className="discard-btn" onClick={() => handleDiscard(c)}>
											<span style={{display:"inline-block",width:10,height:10,borderRadius:"50%",background:GEM_HEX[c],marginRight:6}}/>
											{GEM_LABELS[c]} ({count})
										</button>
									);
								})}
							</div>
							<div className="discard-count">
								Total: {gemTotal(me.tokens)} / 10
							</div>
						</div>
					</div>
				)}

				{toast && <div className="toast">{toast}</div>}
			</div>
		</>
	);

	return (
		<>
			<style>{css}</style>
			<div className="app" style={{display:"flex",alignItems:"center",justifyContent:"center",minHeight:"100vh"}}>
				<p style={{color:"var(--text-dim)",fontStyle:"italic"}}>Loading…</p>
			</div>
		</>
	);
}

