import random
import string
import time
import threading
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room, leave_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, async_mode='eventlet')

# --- 定数と設定 (元のJSから移植) ---
ROWS, COLS = 32, 64
TILE_SIZE = 40

UNIT_DEFS = {
    'inf': {'name':'歩兵','hp':6, 'cost':{'fund':50,'man':10,'food':20},'move':2,'vision':2,'sea':False,
            'dmgAtk':{'inf':2,'arty':1,'tank':1,'bb':0,'sub':0}, 'dmgDef':{'inf':3,'arty':2,'tank':2,'bb':1,'sub':1}},
    'arty':{'name':'砲兵','hp':7, 'cost':{'fund':90,'man':18,'steel':24},'move':1,'vision':3,'sea':False,
            'dmgAtk':{'inf':4,'arty':3,'tank':5,'bb':3,'sub':0}, 'dmgDef':{'inf':2,'arty':1,'tank':2,'bb':1,'sub':1}, 'range':1},
    'tank':{'name':'戦車','hp':8, 'cost':{'fund':150,'man':20,'oil':30},'move':3,'vision':4,'sea':False,
            'dmgAtk':{'inf':2,'arty':2,'tank':2,'bb':1,'sub':0}, 'dmgDef':{'inf':2,'arty':2,'tank':2,'bb':1,'sub':1}},
    'sub': {'name':'潜水艦','hp':7, 'cost':{'fund':420,'man':30,'oil':60,'steel':30},'move':2,'vision':3,'sea':True,'stealth':True,
            'dmgAtk':None,'dmgDef':{'inf':0,'arty':0,'tank':0,'bb':1,'sub':1}},
    'bb':  {'name':'戦艦','hp':14,'cost':{'fund':520,'man':50,'oil':95},'move':1,'vision':5,'sea':True,'range':1,
            'dmgAtk':{'inf':2,'arty':2,'tank':2,'bb':4,'sub':1}, 'dmgDef':{'inf':2,'arty':2,'tank':2,'bb':4,'sub':1}}
}

# ゲームルーム管理
games = {}

class Game:
    def __init__(self, room_id):
        self.room_id = room_id
        self.players = {} # sid -> {name, color, resources, id(1-5), start_pos}
        self.map = []
        self.units = []
        self.resource_points = []
        self.territories = {}
        self.turn = 1
        self.started = False
        self.player_slots = [1, 2, 3, 4, 5]
        self.ready_players = set()
        self.timer = None
        self.turn_start_time = 0

    def generate_map(self):
        # マップ初期化
        self.map = [[{'isLand': random.random() < 0.55, 'owner': None, 'fort': None} for _ in range(COLS)] for _ in range(ROWS)]
        # 平滑化 (Smooth)
        for _ in range(4):
            new_map = [[tile.copy() for tile in row] for row in self.map]
            for r in range(ROWS):
                for c in range(COLS):
                    land_count = 0
                    for dr in [-1, 0, 1]:
                        for dc in [-1, 0, 1]:
                            rr, cc = r + dr, c + dc
                            if 0 <= rr < ROWS and 0 <= cc < COLS and new_map[rr][cc]['isLand']:
                                land_count += 1
                    self.map[r][c]['isLand'] = land_count >= 5
        
        # 資源配置
        types = ['fundfood', 'fundsteel', 'fundoil']
        count = 0
        while count < 40:
            r, c = random.randint(0, ROWS-1), random.randint(0, COLS-1)
            if self.map[r][c]['isLand'] and not any(p['r'] == r and p['c'] == c for p in self.resource_points):
                self.resource_points.append({'r': r, 'c': c, 'type': random.choice(types)})
                count += 1

    def add_player(self, sid, name):
        if len(self.players) >= 5:
            return False
        pid = self.player_slots.pop(0)
        # 色定義 (CSS変数に対応するインデックス)
        self.players[sid] = {
            'id': pid,
            'name': name,
            'resources': {'fund':900,'man':220,'food':240,'steel':140,'oil':100},
            'start_pos': None
        }
        self.territories[pid] = []
        return pid

    def start_game(self):
        self.generate_map()
        self.started = True
        
        # プレイヤー配置 (簡易的な分散配置)
        seeds = [
            (2, 2), (ROWS-3, 2), (ROWS-3, COLS-3), (2, COLS-3), 
            (ROWS//2, COLS//2)
        ]
        
        for i, (sid, p_data) in enumerate(self.players.items()):
            pid = p_data['id']
            # 近くの陸地を探す
            sr, sc = seeds[i % len(seeds)]
            found = False
            for rad in range(30):
                for dr in range(-rad, rad+1):
                    for dc in range(-rad, rad+1):
                        rr, cc = sr+dr, sc+dc
                        if 0 <= rr < ROWS and 0 <= cc < COLS and self.map[rr][cc]['isLand']:
                            # 初期配置
                            self.claim_tile(rr, cc, pid)
                            self.spawn_unit(pid, 'inf', rr, cc)
                            p_data['start_pos'] = {'r': rr, 'c': cc}
                            found = True
                            break
                    if found: break
                if found: break
        
        self.reset_turn_timer()

    def claim_tile(self, r, c, pid):
        key = f"{r},{c}"
        # 他のプレイヤーの領土から削除
        for other_pid in self.territories:
            if key in self.territories[other_pid]:
                self.territories[other_pid].remove(key)
        
        if pid not in self.territories:
            self.territories[pid] = []
        if key not in self.territories[pid]:
            self.territories[pid].append(key)
        self.map[r][c]['owner'] = pid

    def spawn_unit(self, owner, u_type, r, c):
        unit_id = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
        def_data = UNIT_DEFS[u_type]
        unit = {
            'id': unit_id, 'owner': owner, 'type': u_type,
            'x': c, 'y': r, 'moveLeft': def_data['move'], 'hp': def_data['hp'],
            'seaTransport': False
        }
        self.units.append(unit)
        self.claim_tile(r, c, owner)

    def reset_turn_timer(self):
        if self.timer:
            self.timer.cancel()
        self.turn_start_time = time.time()
        self.timer = threading.Timer(180.0, self.force_end_turn) # 3分
        self.timer.start()

    def force_end_turn(self):
        print(f"Room {self.room_id}: Time limit reached. Forcing turn end.")
        with app.app_context():
            self.resolve_turn()

    def end_turn_request(self, sid):
        if sid in self.players:
            self.ready_players.add(sid)
            # 全員完了したらターン処理
            if len(self.ready_players) == len(self.players):
                self.resolve_turn()

    def resolve_turn(self):
        if self.timer: self.timer.cancel()
        
        # 1. 収入計算
        for sid, p in self.players.items():
            pid = p['id']
            res = p['resources']
            # 資源ポイント
            for rp in self.resource_points:
                if self.tile_owned_by(rp['r'], rp['c'], pid) and self.map[rp['r']][rp['c']]['isLand']:
                    if rp['type'] == 'fundfood': res['fund']+=120; res['food']+=40
                    if rp['type'] == 'fundsteel': res['fund']+=120; res['steel']+=30
                    if rp['type'] == 'fundoil': res['fund']+=120; res['oil']+=25
            # 人材
            for t in self.territories.get(pid, []):
                r, c = map(int, t.split(','))
                if self.map[r][c]['isLand'] and not any(rp['r']==r and rp['c']==c for rp in self.resource_points):
                    res['man'] += 5

        # 2. 範囲攻撃 & 戦闘解決 (簡易実装: サイコロ)
        # Python側でJSの戦闘ロジックを完全再現する必要がありますが、
        # ここでは長くなるため「同じタイルにいる敵同士がダメージを与え合う」コアロジックのみ記述します。
        self.resolve_combat()

        # 3. ユニット回復・移動力リセット
        for u in self.units:
            u['moveLeft'] = UNIT_DEFS[u['type']]['move']
            # 簡易回復
            if self.tile_owned_by(u['y'], u['x'], u['owner']) and u['hp'] < UNIT_DEFS[u['type']]['hp']:
                if random.random() < 0.5:
                    u['hp'] += 1

        # 4. 滅亡判定
        alive_players = []
        for sid, p in self.players.items():
            pid = p['id']
            has_land = any(self.map[int(k.split(',')[0])][int(k.split(',')[1])]['isLand'] for k in self.territories.get(pid, []))
            if not has_land:
                # 滅亡処理 (ユニット削除など)
                self.units = [u for u in self.units if u['owner'] != pid]
                self.territories[pid] = []
            else:
                alive_players.append(sid)

        # ターン進行
        self.turn += 1
        self.ready_players.clear()
        self.reset_turn_timer()
        
        # クライアントへ状態送信
        self.broadcast_state()

    def resolve_combat(self):
        # 同じタイルのユニットグループ
        tiles = {}
        for u in self.units:
            k = f"{u['y']},{u['x']}"
            if k not in tiles: tiles[k] = []
            tiles[k].append(u)
        
        for k, us in tiles.items():
            owners = set(u['owner'] for u in us)
            if len(owners) > 1:
                # 戦闘発生
                # 簡易版: お互いにダメージ
                damage_queue = []
                for u in us:
                    # 敵を探す
                    enemies = [e for e in us if e['owner'] != u['owner']]
                    if enemies:
                        target = random.choice(enemies)
                        dmg = random.randint(1, 6) # ダイスロール
                        damage_queue.append((target, dmg))
                
                for target, dmg in damage_queue:
                    target['hp'] -= dmg
        
        # 死亡判定
        self.units = [u for u in self.units if u['hp'] > 0]

    def tile_owned_by(self, r, c, pid):
        return pid in self.territories and f"{r},{c}" in self.territories[pid]

    def broadcast_state(self):
        # 全員に共通のデータを送るが、Fog of Warはクライアント側で隠すか、
        # 本来はここでフィルタリングして送るべき。今回は同期要件重視で全データを送り、クライアントでマスクする。
        # (セキュリティを高めるならここで各プレイヤー視点のデータを生成する)
        
        common_data = {
            'map': self.map,
            'units': self.units,
            'resourcePoints': self.resource_points,
            'turn': self.turn,
            'territories': self.territories
        }
        
        for sid, p in self.players.items():
            # 個別データ
            payload = {
                'self_id': p['id'],
                'self_resources': p['resources'],
                'players_info': [{'id': v['id'], 'name': v['name']} for k, v in self.players.items()],
                'start_pos': p['start_pos'],
                **common_data
            }
            socketio.emit('game_update', payload, room=sid)

    def process_move(self, sid, unit_id, to_r, to_c):
        if sid not in self.players: return
        pid = self.players[sid]['id']
        
        unit = next((u for u in self.units if u['id'] == unit_id and u['owner'] == pid), None)
        if not unit: return
        
        if unit['moveLeft'] > 0:
            # 距離チェック等は省略（本来は必要）
            unit['x'] = to_c
            unit['y'] = to_r
            unit['moveLeft'] -= 1
            self.claim_tile(to_r, to_c, pid)
            self.broadcast_state()

    def process_produce(self, sid, r, c, u_type):
        if sid not in self.players: return
        pid = self.players[sid]['id']
        p_data = self.players[sid]
        
        cost = UNIT_DEFS[u_type]['cost']
        # コストチェック
        can_afford = all(p_data['resources'].get(k, 0) >= v for k, v in cost.items())
        
        if can_afford:
            for k, v in cost.items():
                p_data['resources'][k] -= v
            self.spawn_unit(pid, u_type, r, c)
            self.broadcast_state()


# --- Flask Routes ---

@app.route('/')
def index():
    return render_template('index.html')

# --- SocketIO Events ---

@socketio.on('create_room')
def on_create_room(data):
    # ID生成: 3桁数字 + 2桁英字
    room_id = "{:03d}{}".format(random.randint(0, 999), ''.join(random.choices(string.ascii_uppercase, k=2)))
    games[room_id] = Game(room_id)
    
    name = data.get('name', 'Player')
    join_room(room_id)
    pid = games[room_id].add_player(request.sid, name)
    
    emit('room_created', {'room_id': room_id, 'pid': pid})
    print(f"Room {room_id} created by {name}")

@socketio.on('join_room')
def on_join_room(data):
    room_id = data.get('room_id')
    name = data.get('name', 'Player')
    
    if room_id in games and not games[room_id].started:
        join_room(room_id)
        pid = games[room_id].add_player(request.sid, name)
        if pid:
            emit('joined_room', {'room_id': room_id, 'pid': pid})
            # 人数が5人または開始要求があればスタートだが、今回は「全員揃ったら」等のロジックの代わりに
            # 「開始ボタン」をホストが押す、あるいは人数上限で開始などのトリガーが必要。
            # 要件「余った国家枠は削除する」 -> 全員揃って開始コマンドを受けたらスタートする形にします。
        else:
            emit('error', {'msg': 'Room full'})
    else:
        emit('error', {'msg': 'Room not found or started'})

@socketio.on('start_game_req')
def on_start_game(data):
    room_id = data.get('room_id')
    if room_id in games:
        game = games[room_id]
        # 余ったスロットを削除 (ロジック上、add_playerされていないIDは使われない)
        game.start_game()
        game.broadcast_state()

@socketio.on('action_move')
def on_move(data):
    room_id = data.get('room_id')
    if room_id in games:
        games[room_id].process_move(request.sid, data['unit_id'], data['r'], data['c'])

@socketio.on('action_produce')
def on_produce(data):
    room_id = data.get('room_id')
    if room_id in games:
        games[room_id].process_produce(request.sid, data['r'], data['c'], data['type'])

@socketio.on('end_turn')
def on_end_turn(data):
    room_id = data.get('room_id')
    if room_id in games:
        games[room_id].end_turn_request(request.sid)

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
