"""
Sandbox 3D Multiplayer - Python Desktop App
Requiere: pip install ursina

Controles:
- WASD: Mover
- Espacio: Saltar
- Click izquierdo: Colocar bloque
- Click derecho: Eliminar bloque
- ESC: Salir
"""

import socket
import threading
import json
import time
import sys

try:
    from ursina import *
    from ursina.prefabs.first_person_controller import FirstPersonController
except ImportError:
    print("Instala ursina: pip install ursina")
    sys.exit(1)

# ── Networking ──────────────────────────────────────────────

PORT = 25565
blocks_data = []  # shared block list
remote_players = {}  # id -> entity
my_id = str(id(object()))
running = True

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except:
        return "127.0.0.1"
    finally:
        s.close()

class Server:
    def __init__(self):
        self.clients = []
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("0.0.0.0", PORT))
        self.sock.listen(5)
        self.blocks = []
        threading.Thread(target=self.accept_loop, daemon=True).start()

    def accept_loop(self):
        while running:
            try:
                conn, addr = self.sock.accept()
                self.clients.append(conn)
                # Send existing blocks
                for b in self.blocks:
                    self.send(conn, b)
                threading.Thread(target=self.client_loop, args=(conn,), daemon=True).start()
            except:
                break

    def client_loop(self, conn):
        buf = ""
        while running:
            try:
                data = conn.recv(4096).decode()
                if not data:
                    break
                buf += data
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    msg = json.loads(line)
                    if msg.get("type") == "block":
                        self.blocks.append(msg)
                    self.broadcast(line, exclude=conn)
            except:
                break
        self.clients.remove(conn) if conn in self.clients else None

    def broadcast(self, line, exclude=None):
        for c in self.clients[:]:
            if c != exclude:
                try:
                    c.sendall((line + "\n").encode())
                except:
                    self.clients.remove(c)

    def send(self, conn, msg):
        try:
            conn.sendall((json.dumps(msg) + "\n").encode())
        except:
            pass

class Client:
    def __init__(self, host):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((host, PORT))
        self.on_message = None
        threading.Thread(target=self.recv_loop, daemon=True).start()

    def recv_loop(self):
        buf = ""
        while running:
            try:
                data = self.sock.recv(4096).decode()
                if not data:
                    break
                buf += data
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    msg = json.loads(line)
                    if self.on_message:
                        self.on_message(msg)
            except:
                break

    def send(self, msg):
        try:
            self.sock.sendall((json.dumps(msg) + "\n").encode())
        except:
            pass

# ── Game ────────────────────────────────────────────────────

net_client = None
net_server = None
block_entities = {}

def start_game(is_host, host_ip=None):
    global net_client, net_server, running

    app = Ursina(title="Sandbox 3D Multiplayer", borderless=False)

    if is_host:
        net_server = Server()
        net_client = Client("127.0.0.1")
        ip = get_local_ip()
        ip_text = Text(text=f"IP: {ip}:{PORT}", position=(0.5, 0.48), origin=(1, 0),
                       scale=1.5, color=color.white, background=True)
    else:
        net_client = Client(host_ip)

    # Ground
    ground = Entity(model="plane", scale=(50, 1, 50), texture="white_cube",
                    texture_scale=(50, 50), color=color.rgb(100, 180, 100),
                    collider="box")

    player = FirstPersonController(y=2, speed=5)

    # Block colors
    block_colors = [color.white, color.red, color.blue, color.yellow,
                    color.green, color.orange, color.cyan, color.magenta]
    current_color = [0]

    color_text = Text(text="Color: Blanco (scroll para cambiar)", position=(-0.85, 0.48),
                      scale=1.2, color=color.white, background=True)

    color_names = ["Blanco", "Rojo", "Azul", "Amarillo", "Verde", "Naranja", "Cyan", "Magenta"]

    def place_block(pos, col_idx, from_net=False):
        key = (round(pos[0]), round(pos[1]), round(pos[2]))
        if key in block_entities:
            return
        b = Entity(model="cube", position=Vec3(*key), color=block_colors[col_idx % len(block_colors)],
                   texture="white_cube", collider="box", scale=1)
        block_entities[key] = b
        if not from_net and net_client:
            net_client.send({"type": "block", "action": "place",
                             "pos": list(key), "color": col_idx, "pid": my_id})

    def remove_block(pos, from_net=False):
        key = (round(pos[0]), round(pos[1]), round(pos[2]))
        if key in block_entities:
            destroy(block_entities.pop(key))
            if not from_net and net_client:
                net_client.send({"type": "block", "action": "remove",
                                 "pos": list(key), "pid": my_id})

    def handle_net_msg(msg):
        if msg.get("type") == "block":
            invoke(lambda: _handle_block(msg), delay=0)
        elif msg.get("type") == "pos":
            invoke(lambda: _handle_pos(msg), delay=0)

    def _handle_block(msg):
        pos = tuple(msg["pos"])
        if msg["action"] == "place":
            place_block(pos, msg.get("color", 0), from_net=True)
        elif msg["action"] == "remove":
            remove_block(pos, from_net=True)

    def _handle_pos(msg):
        pid = msg["pid"]
        if pid == my_id:
            return
        p = msg["pos"]
        if pid not in remote_players:
            remote_players[pid] = Entity(model="cube", color=color.azure,
                                          scale=(0.8, 1.8, 0.8))
        remote_players[pid].position = Vec3(p[0], p[1], p[2])

    net_client.on_message = handle_net_msg

    pos_timer = [0]

    def update():
        pos_timer[0] += time.dt
        if pos_timer[0] > 0.1:
            pos_timer[0] = 0
            if net_client:
                net_client.send({"type": "pos", "pid": my_id,
                                 "pos": [player.x, player.y, player.z]})

    def input(key):
        if key == "left mouse down":
            hit = raycast(camera.world_position, camera.forward, distance=8, ignore=[player,])
            if hit.hit:
                place_block(hit.entity.position + hit.normal, current_color[0])
        elif key == "right mouse down":
            hit = raycast(camera.world_position, camera.forward, distance=8, ignore=[player,])
            if hit.hit and hit.entity != ground:
                remove_block(hit.entity.position)
        elif key == "scroll up":
            current_color[0] = (current_color[0] + 1) % len(block_colors)
            color_text.text = f"Color: {color_names[current_color[0]]} (scroll para cambiar)"
        elif key == "scroll down":
            current_color[0] = (current_color[0] - 1) % len(block_colors)
            color_text.text = f"Color: {color_names[current_color[0]]} (scroll para cambiar)"

    app.update = update
    app.input = input

    Sky()
    app.run()
    running = False

# ── Menu ────────────────────────────────────────────────────

def main():
    app = Ursina(title="Sandbox 3D - Menú", borderless=False, size=(600, 400))

    title = Text(text="🎮 Sandbox 3D Multiplayer", scale=3, y=0.35, origin=(0, 0),
                 color=color.white)
    subtitle = Text(text="Construye con amigos en 3D", scale=1.5, y=0.22, origin=(0, 0),
                    color=color.light_gray)

    result = {"mode": None, "ip": None}

    def on_create():
        result["mode"] = "host"
        application.quit()

    ip_field = InputField(default_value="192.168.1.X", y=-0.08, scale=(0.6, 0.06))

    def on_join():
        result["mode"] = "join"
        result["ip"] = ip_field.text.strip()
        application.quit()

    Button(text="Crear Partida", scale=(0.4, 0.08), y=0.05, color=color.azure,
           highlight_color=color.cyan, on_click=on_create)
    Button(text="Unirse", scale=(0.4, 0.08), y=-0.18, color=color.green,
           highlight_color=color.lime, on_click=on_join)

    Text(text="Escribe la IP del host para unirte:", scale=1, y=-0.01, origin=(0, 0),
         color=color.light_gray)

    app.run()

    if result["mode"] == "host":
        start_game(is_host=True)
    elif result["mode"] == "join" and result["ip"]:
        start_game(is_host=False, host_ip=result["ip"])

if __name__ == "__main__":
    main()
