const socket = io();
let myRoomId = null;
let myPid = null;
let myStartPos = {r:0, c:0};

// Game State
let mapData = [];
let units = [];
let resources = [];
let territories = {};
let myResources = {};
let playersInfo = [];

// Viewport & Input
const canvas = document.getElementById('map');
const ctx = canvas.getContext('2d');
const TILE = 40;
let viewportX = 0, viewportY = 0;
let selectedTile = null;
let tileMode = null; // 'move' or null

// --- Network Functions ---
function createRoom() {
    const name = document.getElementById('playerName').value || 'Player';
    socket.emit('create_room', {name: name});
}

function joinRoom() {
    const name = document.getElementById('playerName').value || 'Player';
    const rid = document.getElementById('roomIdInput').value;
    socket.emit('join_room', {room_id: rid, name: name});
}

function startGame() {
    socket.emit('start_game_req', {room_id: myRoomId});
}

function sendEndTurn() {
    socket.emit('end_turn', {room_id: myRoomId});
    document.getElementById('endTurnBtn').disabled = true;
    document.getElementById('endTurnBtn').innerText = "待機中...";
}

// --- Socket Handlers ---
socket.on('room_created', (data) => {
    myRoomId = data.room_id;
    myPid = data.pid;
    enterWaitingRoom(true);
});

socket.on('joined_room', (data) => {
    myRoomId = data.room_id;
    myPid = data.pid;
    enterWaitingRoom(false);
});

socket.on('error', (data) => {
    alert(data.msg);
});

socket.on('game_update', (data) => {
    // ゲーム画面表示
    document.getElementById('onlineMenu').classList.add('hidden');
    document.getElementById('gameContainer').classList.remove('hidden');
    
    // 状態更新
    mapData = data.map;
    units = data.units;
    resources = data.resourcePoints;
    territories = data.territories;
    myResources = data.self_resources;
    myStartPos = data.start_pos;
    playersInfo = data.players_info;
    document.getElementById('turnDisplay').innerText = data.turn;

    // ボタン復活
    const btn = document.getElementById('endTurnBtn');
    btn.disabled = false;
    btn.innerText = "ターン終了";

    updateUI();
    recalcFog(); // 簡易FOG
    render();
    
    // 初回のみ視点移動
    if(data.turn === 1 && viewportX === 0 && viewportY === 0) {
        resetViewport();
    }
});

function enterWaitingRoom(isHost) {
    document.getElementById('lobby').classList.add('hidden');
    document.getElementById('waitingRoom').classList.remove('hidden');
    document.getElementById('roomDisplay').innerText = `Room: ${myRoomId}`;
    if(isHost) document.getElementById('startGameBtn').classList.remove('hidden');
}

// --- Game Logic & Render ---

// 簡易Fog of War計算 (クライアント側でマスク処理)
function recalcFog() {
    // サーバーから全データが来るが、描画時に自分の視界外を隠す
    // 本来はサーバーで計算すべきだが、移植の簡便さのためここで計算
    for(let r=0; r<32; r++) for(let c=0; c<64; c++) {
        mapData[r][c].visible = false;
    }
    
    // 自分の領土
    if(territories[myPid]) {
        territories[myPid].forEach(key => {
            const [r,c] = key.split(',').map(Number);
            mapData[r][c].visible = true;
        });
    }
    
    // 自分のユニット
    units.filter(u => u.owner === myPid).forEach(u => {
        const vis = (u.type === 'bb') ? 5 : (u.type === 'tank') ? 4 : 2;
        for(let dr=-vis; dr<=vis; dr++) for(let dc=-vis; dc<=vis; dc++) {
            const rr = u.y+dr, cc = u.x+dc;
            if(rr>=0 && rr<32 && cc>=0 && cc<64) mapData[rr][cc].visible = true;
        }
    });
}

function render() {
    ctx.clearRect(0,0,canvas.width,canvas.height);
    
    const rows = 18; // 720 / 40
    const cols = 25; // 1000 / 40

    for(let r=viewportY; r < Math.min(32, viewportY+rows); r++) {
        for(let c=viewportX; c < Math.min(64, viewportX+cols); c++) {
            const x = (c - viewportX) * TILE;
            const y = (r - viewportY) * TILE;
            const tile = mapData[r][c];
            const visible = tile.visible;

            // 地形
            ctx.fillStyle = tile.isLand ? '#ffffff' : '#00ccff';
            ctx.fillRect(x, y, TILE, TILE);
            
            if(!visible) {
                ctx.fillStyle = 'rgba(0,0,0,0.7)';
                ctx.fillRect(x, y, TILE, TILE);
                ctx.strokeStyle='#222'; ctx.strokeRect(x,y,TILE,TILE);
                continue; // 視界外なら詳細描画しない
            }

            // 領土色
            if(tile.owner) {
                // 簡易色分け (本来はCSS変数と同期)
                const colors = {1:'#22c55e', 2:'#ef4444', 3:'#3b82f6', 4:'#f97316', 5:'#8b5cf6'};
                ctx.fillStyle = colors[tile.owner] ? colors[tile.owner] + '44' : '#99999944';
                ctx.fillRect(x,y,TILE,TILE);
            }

            // 資源
            const res = resources.find(p=>p.r===r && p.c===c);
            if(res) {
                ctx.fillStyle='#ffd27f'; ctx.beginPath(); ctx.arc(x+20,y+20,7,0,Math.PI*2); ctx.fill();
            }
            
            // ユニット
            const unit = units.find(u=>u.x===c && u.y===r);
            if(unit) {
                // 敵ユニットは見えている場合のみ
                if(unit.owner === myPid || visible) {
                    ctx.fillStyle = (unit.owner === myPid) ? '#0fb5ff' : '#ff0000';
                    ctx.fillRect(x+10, y+10, 20, 20);
                    // HP Bar
                    ctx.fillStyle='black'; ctx.fillRect(x+10, y+32, 20, 4);
                    ctx.fillStyle='lime'; ctx.fillRect(x+10, y+32, (unit.hp/10)*20, 4); // 簡易HP表示
                }
            }
            
            // 選択枠
            if(selectedTile && selectedTile.r===r && selectedTile.c===c) {
                ctx.strokeStyle = '#facc15'; ctx.lineWidth=3;
                ctx.strokeRect(x,y,TILE,TILE);
            }
        }
    }
}

// Input Handling
canvas.addEventListener('click', e => {
    const rect = canvas.getBoundingClientRect();
    const c = Math.floor((e.clientX - rect.left) / TILE) + viewportX;
    const r = Math.floor((e.clientY - rect.top) / TILE) + viewportY;
    
    if(r<0 || r>=32 || c<0 || c>=64) return;
    
    // 移動モード
    if(tileMode === 'move' && selectedTile) {
        const u = units.find(u => u.x === selectedTile.c && u.y === selectedTile.r && u.owner === myPid);
        if(u) {
            // サーバーへ移動要求
            socket.emit('action_move', {
                room_id: myRoomId,
                unit_id: u.id,
                r: r,
                c: c
            });
            tileMode = null;
            selectedTile = null;
            document.getElementById('actionPanel').style.display='none';
            return;
        }
    }
    selectedTile = {r, c};
    document.getElementById('selInfo').innerText = `(${r},${c})`;
    
    const u = units.find(u => u.x === c && u.y === r && u.owner === myPid);
    const tile = mapData[r][c];
    
    // アクションパネル表示
    const panel = document.getElementById('actionPanel');
    if(u && u.moveLeft > 0) {
        panel.style.display = 'block';
        document.getElementById('moveModeBtn').style.display = 'inline';
    } else {
        document.getElementById('moveModeBtn').style.display = 'none';
    }
    
    // 生産パネル
    if(tile.owner === myPid && tile.isLand && !u) {
         panel.style.display = 'block';
         document.getElementById('prodPanel').style.display = 'block';
    } else {
         document.getElementById('prodPanel').style.display = 'none';
    }
    
    render();
});

document.getElementById('moveModeBtn').addEventListener('click', () => {
    tileMode = 'move';
    document.getElementById('selInfo').innerText += " [移動先を選択]";
});

function doProduce() {
    const type = document.getElementById('prodType').value;
    if(selectedTile) {
        socket.emit('action_produce', {
            room_id: myRoomId,
            r: selectedTile.r,
            c: selectedTile.c,
            type: type
        });
        selectedTile = null;
        document.getElementById('actionPanel').style.display='none';
    }
}

function updateUI() {
    const r = myResources;
    const box = document.getElementById('resources');
    box.innerHTML = `
        <div class="res">資金 ${r.fund}</div>
        <div class="res">人材 ${r.man}</div>
        <div class="res">食料 ${r.food}</div>
        <div class="res">鉄鋼 ${r.steel}</div>
        <div class="res">石油 ${r.oil}</div>
    `;
    
    const myInfo = playersInfo.find(p => p.id === myPid);
    if(myInfo) document.getElementById('countryLabel').innerText = myInfo.name;
}

// ◎ボタン: 初期視点へ
function resetViewport() {
    if(myStartPos) {
        // 画面中央に初期位置が来るように調整
        viewportY = Math.max(0, Math.min(32-18, myStartPos.r - 9));
        viewportX = Math.max(0, Math.min(64-25, myStartPos.c - 12));
        render();
    }
}
window.addEventListener('keydown', (e) => {
    if(document.getElementById('onlineMenu').style.display !== 'none') return;
    if(e.key === 'ArrowUp') viewportY = Math.max(0, viewportY-1);
    if(e.key === 'ArrowDown') viewportY = Math.min(32-18, viewportY+1);
    if(e.key === 'ArrowLeft') viewportX = Math.max(0, viewportX-1);
    if(e.key === 'ArrowRight') viewportX = Math.min(64-25, viewportX+1);
    render();
});
function scrollMap(dx, dy) {
    const ROWS = 32;
    const COLS = 64;
    const rowsOnScreen = Math.floor(canvas.height / TILE);
    const colsOnScreen = Math.floor(canvas.width / TILE);
    if (dx === 0 && dy === 0) {
        logToUI("ズーム機能は未実装です。");
        return;
    }
    if (dx !== 0) {
        viewportX = Math.max(0, Math.min(COLS - colsOnScreen, viewportX + dx));
    }
    if (dy !== 0) {
        viewportY = Math.max(0, Math.min(ROWS - rowsOnScreen, viewportY + dy));
    }

    render();
}
function logToUI(message) {
    const logDiv = document.getElementById('log');
    logDiv.innerHTML = `<div class="small">${message}</div>` + logDiv.innerHTML;
}
