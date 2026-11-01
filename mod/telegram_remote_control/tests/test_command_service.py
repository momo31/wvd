"""Polling tests use a synchronous fake client; no Telegram connection is made."""

import queue
import unittest
from unittest.mock import Mock

from mod.telegram_remote_control.bot_api import TelegramTransientError
from mod.telegram_remote_control.command_service import TelegramCommandService
from mod.telegram_remote_control.models import RemoteCommand, TelegramSettings


def stop_update(update_id=101, chat_id=123456789):
    return {"update_id": update_id, "message": {
        "chat": {"id": chat_id, "type": "private"},
        "from": {"is_bot": False}, "text": "/stop",
    }}


class PollingTests(unittest.TestCase):
    def run_poll(self, responses, *, fail_command_once=False):
        events = queue.Queue()
        put = events.put

        def deliver(event):
            nonlocal fail_command_once
            if event[0] == "telegram_command" and fail_command_once:
                fail_command_once = False
                raise queue.Full()
            put(event)

        events.put = deliver
        client = Mock()
        service = TelegramCommandService(events, Mock(), client_factory=lambda *_: client)
        service._settings = TelegramSettings(True, "fake-token", "123456789")
        service._generation = 1
        service._wait_for_change = Mock()
        replies = iter(responses)
        offsets = []

        def get_updates(offset, **_):
            offsets.append(offset)
            try:
                response = next(replies)
            except StopIteration:
                service._final_stop = True
                return []
            if isinstance(response, Exception):
                raise response
            if callable(response):
                return response(service)
            return response

        client.get_updates.side_effect = get_updates
        service._poll_loop()
        return service, offsets, [payload for kind, payload in list(events.queue) if kind == "telegram_command"]

    def test_reconnect_delivers_pending_stop_exactly_once(self):
        service, offsets, commands = self.run_poll([
            [{"update_id": 100}], TelegramTransientError("offline"),
            [stop_update(), stop_update()], [stop_update()],
        ])
        self.assertEqual(offsets, [-1, 101, 101, 102, 102])
        self.assertEqual([c.command for c in commands], [RemoteCommand.STOP])
        self.assertEqual(service._last_update_id, 101)

    def test_bootstrap_discards_old_commands_once_even_with_empty_backlog(self):
        _, offsets, commands = self.run_poll([
            [], TimeoutError(), [stop_update()],
        ])
        self.assertEqual(offsets, [-1, None, None, 102])
        self.assertEqual(len(commands), 1)
        _, _, commands = self.run_poll([[stop_update()], []])
        self.assertEqual(commands, [])

    def test_old_generation_response_is_ignored_and_new_generation_bootstraps(self):
        def reconfigure(service):
            service._generation += 1
            service._last_update_id = None
            return [stop_update()]

        _, offsets, commands = self.run_poll([
            [{"update_id": 100}], reconfigure, [{"update_id": 200}], [stop_update(201)],
        ])
        self.assertEqual(offsets, [-1, 101, -1, 201, 202])
        self.assertEqual([(c.update_id, c.service_generation) for c in commands], [(201, 2)])

    def test_invalid_updates_and_unauthorized_chat_do_not_block_valid_stop(self):
        _, offsets, commands = self.run_poll([
            [], [{"update_id": "bad"}, None, stop_update(99, 999), stop_update()],
        ])
        self.assertEqual(offsets, [-1, None, 102])
        self.assertEqual(len(commands), 1)

    def test_offset_only_advances_after_command_delivery(self):
        _, offsets, commands = self.run_poll([
            [{"update_id": 100}], [stop_update()], [stop_update()],
        ], fail_command_once=True)
        self.assertEqual(offsets, [-1, 101, 101, 102])
        self.assertEqual(len(commands), 1)


if __name__ == "__main__":
    unittest.main()
