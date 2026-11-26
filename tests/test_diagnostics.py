import unittest
from unittest.mock import Mock

from dingdong.transport import SerialLink, Reply, LinkError


class ExitDiagnosticsTests(unittest.TestCase):
    def test_signed_sticks_and_unsigned_buttons_and_triggers(self):
        link = SerialLink.__new__(SerialLink)
        link.request = Mock(side_effect=[Reply(0, 0, 1, -32752),
            Reply(0, 0, 0x11EF, -32768), Reply(0, 0, -256, 0)])
        result = link.exit_diagnostics()
        self.assertIn("手柄输入(1)", result)
        self.assertIn("K1=0x10, K2=0x80", result)
        self.assertIn("LX=-17, LY=17, RX=0, RY=-128", result)
        self.assertIn("LT=0, RT=255", result)
        self.assertEqual([c.args[0] for c in link.request.call_args_list], [0x15, 0x16, 0x17])

    def test_unsupported_firmware_has_explicit_error(self):
        link = SerialLink.__new__(SerialLink)
        link.request = Mock(return_value=Reply(1, 0, 0, 0))
        with self.assertRaises(LinkError):
            link.exit_diagnostics()
