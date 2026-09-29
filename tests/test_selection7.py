import unittest
from isaac_link.selection import Selector,ControlSelector,quality

class Policies(unittest.TestCase):
    def test_stable_small_differences_and_two_rounds(self):
        s=Selector(current='steam',switched=0)
        self.assertEqual(s.choose({'steam':50,'ipv4':45},{'steam','ipv4'},90,3),'steam')
        self.assertEqual(s.choose({'steam':50,'ipv4':25},{'steam','ipv4'},120,4),'steam')
        self.assertEqual(s.choose({'steam':50,'ipv4':25},{'steam','ipv4'},121,4),'steam')
        self.assertEqual(s.choose({'steam':50,'ipv4':25},{'steam','ipv4'},150,5),'ipv4')
        s.commit('ipv4',150)
        self.assertEqual(s.choose({'steam':1,'ipv4':25},{'steam','ipv4'},180,6),'ipv4')

    def test_failure_does_not_wait_for_round_or_cooldown(self):
        s=Selector(current='ipv4',switched=100)
        self.assertEqual(s.choose({'steam':90},{'steam'},101),'steam')
        s.fixed='ipv4';self.assertIsNone(s.choose({'steam':90},{'steam'},102))

    def test_control_priority_hold_and_strict_lock(self):
        s=ControlSelector()
        self.assertEqual(s.choose({'steam'},{'steam':5},0),'steam')
        self.assertEqual(s.choose({'steam','relay'},{'relay':100},1),'steam')
        self.assertEqual(s.choose({'steam','relay'},{'relay':100},6),'relay')
        self.assertEqual(s.choose({'ipv4','lan'},{'ipv4':2,'lan':10},7),'lan')
        s.fixed='relay';self.assertIsNone(s.choose({'steam'},{},8))

    def test_worse_direction_and_invalid_measurement(self):
        self.assertEqual(quality(dict(received=9,p95=20,loss=.1),dict(received=10,p95=30,loss=0)),130)
        self.assertEqual(quality(dict(received=1,p95=1,loss=0),dict(received=10,p95=2,loss=0)),float('inf'))

if __name__=='__main__':unittest.main()
