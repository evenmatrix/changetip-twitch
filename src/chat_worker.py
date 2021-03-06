from irc.bot import IRCDict, Channel, SingleServerIRCBot
import Queue
import threading
import logging
import socks
import socket


class TwitchIRCBot(SingleServerIRCBot):

    def __init__(self, master, worker_name, bot_name, server, access_token, port=6667, proxy=None):
        self.master = master
        self.worker_name = worker_name
        self.command = "!"+self.master.bot_name
        self.started = False
        self.is_connected = False

        if proxy is not None:
            logging.info('[%s] Proxy set: %s:%s', self.worker_name, proxy["address"], proxy["port"])
            socks.set_default_proxy(socks.HTTP, proxy["address"], proxy["port"])
            socket.socket = socks.socksocket

        SingleServerIRCBot.__init__(self, [(server, port, access_token)], bot_name, bot_name)

        # keep ip for logging
        self.proxy_name = socket.gethostbyname(socket.getfqdn())

        # Channels set up
        self.channels = IRCDict()
        self.channel_join_queue = Queue.Queue()
        self.channel_list = []

        # Messages set up
        self.user_message_queue = Queue.Queue()

        self.log('Chat worker bot initialized.')

    def log(self, message):
        logging.info('[%s]:[%s] %s', self.proxy_name, self.worker_name, message)


    def on_welcome(self, serv, event):
        self.is_connected = True
        if not self.started:
            self.log('Connected to Twitch.tv IRC.')
            # Start channel joining thread
            threading.Thread(target=self.channel_joiner, args=(serv,)).start()
            # Start message sending thread
            threading.Thread(target=self.message_sender, args=(serv,)).start()
            self.started = True
        # Welcome is a reconnect, rejoin all channels
        else:
            self.log('Reconnected to Twitch.tv IRC.')
            for channel in self.channel_list:
                self.channel_join_queue.put(channel)

    def on_disconnect(self, serv, event):
        self.is_connected = False

        event_str = str(event)
        e_type = event.type
        e_source = event.source
        e_target = event.target

        logging.warning('[%s] Lost connection to Twitch.tv IRC.', self.worker_name)
        logging.warning('[%s] Event info: %s %s %s', self.worker_name, e_type, e_source, e_target)
        logging.warning('[%s] Even more info: %s ', self.worker_name, event_str)
        logging.warning('[%s] Attempting to reconnect...', self.worker_name)

    def on_pubmsg(self, serv, event):
        message = ''.join(event.arguments).strip()
        author = event.source.nick
        channel = event.target

        if message.lower().startswith(self.command.lower()+" ") or message.lower() == self.command.lower():
            self.master.process_message(self.worker_name, channel, author, message[len(self.command):].strip())

    # Thread for joining channels, capped at a limit of 50 joins per 15 seconds to follow twitch's restrictions
    # 50 joins / 15 seconds = Join up to 5 channels every 1.5 seconds
    def channel_joiner(self, serv):
        join_count = 0
        join_limit = 1
        while not self.channel_join_queue.empty() and join_count < join_limit:
            if self.is_connected:
                channel = self.channel_join_queue.get()
                self.channels[channel] = Channel()
                self.channel_list.append(channel)
                serv.join(channel)
                self.log("Joining channel %s" % channel)
                join_count += 1
        threading.Timer(1.5, self.channel_joiner, args=(serv,)).start()

    # Thread for sending messages, capped at a limit of 20 messages per 30 seconds to follow twitch's restrictions
    # 20 messages / 30 seconds = Send 1 message every 1.5 seconds
    def message_sender(self, serv):

        if self.is_connected and self.master.message_center.has_message(self.worker_name):
            mdata = self.master.message_center.get_message(self.worker_name)
            message = mdata["message"]
            channel = mdata["channel"]

            if message != self.master.message_center.last_message: # Do not send the same message twice
                serv.privmsg(channel, message)
                self.master.message_center.last_message = message
                logging.info("[%s] %s %s: %s", self.worker_name, channel, self.master.bot_name, message)

        threading.Timer(1.5, self.message_sender, args=(serv,)).start()
