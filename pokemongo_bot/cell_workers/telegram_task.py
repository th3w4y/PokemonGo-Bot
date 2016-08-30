# -*- coding: utf-8 -*-

from datetime import datetime
from datetime import timedelta
import os
import json
import telegram
from pokemongo_bot.base_task import BaseTask
from pokemongo_bot.base_dir import _base_dir
from pokemongo_bot.event_handlers import TelegramHandler

class FileIOException(Exception):
    pass

class TelegramTask(BaseTask):
    SUPPORTED_TASK_API_VERSION = 1
    update_id = None
    tbot = None
    min_interval = None
    next_job = None

    def initialize(self):
        if not self.enabled:
            return
        api_key = self.bot.config.telegram_token
        if api_key is None:
            self.emit_event(
                'config_error',
                formatted='api_key not defined.'
            )
            return
        self.tbot = telegram.Bot(api_key)
        self.master = self.config.get('master', None)
        if self.master:
            self.bot.event_manager.add_handler(TelegramHandler(self.tbot, self.master, self.config.get('alert_catch')))
        try:
            self.update_id = self.tbot.getUpdates()[0].update_id
        except IndexError:
            self.update_id = None
        self.min_interval = self.config.get('min_interval', 120)
        self.next_job = datetime.now() + timedelta(seconds=self.min_interval)
    def work(self):
        if not self.enabled:
            return
        if datetime.now() < self.next_job:
            return
        self.next_job = datetime.now() + timedelta(seconds=self.min_interval)
        for update in self.tbot.getUpdates(offset=self.update_id, timeout=10):
            self.update_id = update.update_id+1
            if update.message:
                self.bot.logger.info("message from {} ({}): {}".format(update.message.from_user.username, update.message.from_user.id, update.message.text))
                if self.config.get('master', None) and self.config.get('master', None) not in [update.message.from_user.id, "@{}".format(update.message.from_user.username)]:
                    self.emit_event(
                        'debug',
                        formatted="Master wrong: expecting {}, got {}({})".format(self.master, update.message.from_user.username, update.message.from_user.id))
                    continue
                else:
                    if not re.match(r'^[0-9]+$', "{}".format(self.config['master'])): # master was not numeric...
                        self.config['master'] = update.message.chat_id
                        idx = (i for i,v in enumerate(self.bot.event_manager._handlers) if type(v) is TelegramHandler).next()
                        self.bot.event_manager._handlers[idx] = TelegramHandler(self.tbot, self.master, self.config.get('alert_catch'))
                if update.message.text == "/info":
                    stats = self._get_player_stats()
                    if stats:
                        with self.bot.database as conn:
                            cur = conn.cursor()
                            cur.execute("SELECT DISTINCT COUNT(encounter_id) FROM catch_log WHERE dated >= datetime('now','-1 day')")
                            catch_day = cur.fetchone()[0]
                            cur.execute("SELECT DISTINCT COUNT(pokestop) FROM pokestop_log WHERE dated >= datetime('now','-1 day')")
                            ps_day = cur.fetchone()[0]
                            res = (
                                "*"+self.bot.config.username+"*",
                                "_Level:_ "+str(stats["level"]),
                                "_XP:_ "+str(stats["experience"])+"/"+str(stats["next_level_xp"]),
                                "_Pokemons Captured:_ "+str(stats["pokemons_captured"])+" ("+str(catch_day)+" _last 24h_)",
                                "_Poke Stop Visits:_ "+str(stats["poke_stop_visits"])+" ("+str(ps_day)+" _last 24h_)",
                                "_KM Walked:_ "+str(stats["km_walked"])
                            )
                            self.send_message(chat_id=update.message.chat_id, parse_mode='Markdown', text="\n".join(res))
                            self.send_location(chat_id=update.message.chat_id, latitude=self.bot.api._position_lat, longitude=self.bot.api._position_lng)
                    else:
                        self.send_message(chat_id=update.message.chat_id, parse_mode='Markdown', text="Stats not loaded yet\n")
                elif update.message.text == "/start" or update.message.text == "/help":
                    res = (
                        "Commands: ",
                        "/info - info about bot"
                    )
                    self.send_message(chat_id=update.message.chat_id, parse_mode='Markdown', text="\n".join(res))
    def send_message(self, chat_id, parse_mode, text):
        try:
            self.tbot.sendMessage(chat_id, parse_mode, text)
        except telegram.error.NetworkError:
            pass
    def send_location(self, chat_id, latitude, longitude):
        try:
            self.tbot.send_location(chat_id, latitude, longitude)
        except telegram.error.NetworkError:
            pass
    def _get_player_stats(self):
        """
        Helper method parsing the bot inventory object and returning the player stats object.
        :return: The player stats object.
        :rtype: dict
        """
        web_inventory = os.path.join(_base_dir, "web", "inventory-%s.json" % self.bot.config.username)

        try:
            with open(web_inventory, "r") as infile:
                json_inventory = json.load(infile)
        except ValueError as exception:
            # Unable to read json from web inventory
            # File may be corrupt. Create a new one.
            self.bot.logger.info('[x] Error while opening inventory file for read: %s' % exception)
            json_inventory = []
        except:
            raise FileIOException("Unexpected error reading from {}".format(web_inventory))

        return next((x["inventory_item_data"]["player_stats"]
                     for x in json_inventory
                     if x.get("inventory_item_data", {}).get("player_stats", {})),
                    None)
