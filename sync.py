"""
Usage:
  1. start vlc with command `vlc --intf telnet`
  2. run script
  3. profit
"""

import vlcclient, redis, json, thread, sys, os
import subprocess


MASTER_COMMANDS = """
Commands:
  play     - start/unpause the video
  pause    - pause the video
  allsync  - force all the clients to sync
  quit     - quit the session
  status   - show the session status
  load     - load file at path
"""

GEN_COMMANDS = """
Commands:
  quit - quit the session
  sync - resync the clients video
  load - load file at path
"""

def load_config():
    if os.path.exists("config.json"):
        with open("config.json", "r") as f:
            return json.load(f)
    else:
        with open("config.json", "w") as f:
            f.write("""
                {
                    "host": "yolo.com",
                    "pw": "yolo.com"
                }
                """)
        print "Edit config at config.json"
        sys.exit()

def command_help(self, var):
    if self.isMaster:
        print MASTER_COMMANDS
    else:
        print GEN_COMMANDS

def command_play(self, var):
    if not self.isMaster: return
    print "Starting Playback"
    self.sendFrame()
    self.c.play()
    self.send({
        "tag": "play",
    })

def command_pause(self, var):
    if not self.isMaster: return
    print "Pausing Playback"
    self.sendFrame()
    self.c.pause()
    self.send({
        "tag": "pause"
    })

def command_allsync(self, var):
    if not self.isMaster: return
    print "Syncing all clients"
    self.sendFrame(force=True)

def command_quit(self, var):
    sys.exit()

def command_sync(self, var):
    if self.isMaster: return
    print "Requesting sync from master"
    self.send({
        "tag": "sync"
    })

def command_status(self, var):
    if not self.isMaster: return
    print """
    Room:    %s
    Members: %s
    Playing: %s
    """ % (
        self.room, self.getRoomSize(self.room), bool(self.getVar("is_playing")))

def command_load(self, var):
    if not len(var):
        print "You must give a file to load!"
        return
    if not os.path.exists(var[0]):
        print "No file at path `%s`" % var[0]
        return
    print "Adding file..."
    self.c.add(var[0])

def build_command_dictionary(commands):
    base = {}

    for name, f in commands.items():
        cur = ""
        for char in name:
            cur += char
            if cur in base:
                del base[cur]
                continue
            base[cur] = f
    return base

commands = build_command_dictionary({
    "help": command_help,
    "play": command_play,
    "pause": command_pause,
    "allsync": command_allsync,
    "quit": command_quit,
    "sync": command_sync,
    "status": command_status,
    "load": command_load
})

class Sync(object):
    def __init__(self, room="movie"):
        self.room = room

        config = load_config()

        self.r = redis.Redis(host=config.get("host"), password=config.get("pw"))
        self.ps = self.r.pubsub()

        self.setupVLC()

        self.isMaster = False
        self.join = True
        self.active = True

    def setupVLC(self):
        self.c = vlcclient.VLCClient("localhost")
        self.c.connect()

    def getVar(self, name):
        try:
            data = self.c._send_command(name)
        except:
            setupVLC()
            return self.getVar(name)

        if data.isdigit():
            return int(data)
        return data

    def getTime(self):
        return int(self.c._send_command("get_time"))

    def send(self, obj):
        self.r.publish(self.room, json.dumps(obj))

    def sendFrame(self, force=False):
        self.send({
            "tag": "update",
            "pos": self.getVar("get_time"),
            "len": self.getVar("get_length"),
            "playing": self.getVar("is_playing"),
            "sync": force,
        })

    def handleUpdate(self, data):
        # If the time is different, seek to the right spot
        if abs(self.getVar("get_time") - data['pos']) > 1:
            print "There is an offset in times, adjusting our playback"
            self.c.seek(data['pos'])

        if not data['playing'] == self.getVar("is_playing"):
            print "States are different, adjusting"
            if self.getVar("is_playing"):
                self.c.pause()
            else:
                self.c.play()

    def getRoomSize(self, r):
        return int(self.r.execute_command("PUBSUB", "NUMSUB", r)[1])

    def redisLoop(self):
        if not self.getRoomSize(self.room):
            self.isMaster = True

        self.ps.subscribe(self.room)

        for data in self.ps.listen():
            # If we're subscribing
            if data['type'] == "subscribe":
                # If we're the master
                if self.isMaster:
                    # We send an update frame
                    self.sendFrame()
            else:
                data = json.loads(data['data'])

                if not self.isMaster:
                    if data['tag'] == "sync":
                        self.sendFrame()
                    elif data['tag'] == "play":
                        self.c.play()
                    elif data['tag'] == "pause":
                        self.c.pause()
                    elif data['tag'] == "update":
                        self.handleUpdate(data)

    def run(self):
        thread.start_new_thread(self.redisLoop, ())

        while True:
            try:
                data = raw_input("> ").split(" ", 1)
                if len(data) > 1:
                    command = data[0]
                    args = data[1].split(" ")
                else:
                    command = data[0]
                    args = []
                if command in commands.keys():
                    commands[command](self, args)
                else:
                    print "No command `%s`..." % command
            except KeyboardInterrupt:
                print "Qutting..."
                self.active = False
                self.ps.unsubscribe(self.room)
                sys.exit()

room = sys.argv[1] if len(sys.argv) > 1 else "movieroom"
s = Sync(room)
s.run()
