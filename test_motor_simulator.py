# SPDX-License-Identifier: GPL-3.0-only
"""Solver-free tests for parameter handling and winding geometry."""
import copy,cmath,math,tempfile,unittest
from unittest.mock import patch
from pathlib import Path
import motor_simulator as sim

class ParameterTests(unittest.TestCase):
    def setUp(self):self.cfg=sim.read_parameters(Path(__file__).with_name('motor_parameters.example.ini'))
    def test_known_project_geometry(self):
        g=sim.derive(self.cfg)
        self.assertEqual((g['count'],g['turns']),(12,72))
        self.assertAlmostEqual(g['copper_g'],78.3532765272858,places=9)
        self.assertAlmostEqual(g['outer_mm'],19.816)
        self.assertAlmostEqual(g['R_series_phase20_Ohm'],1.2930525134941897)
    def test_magnet_and_spacer_dimensions_really_change_pitch(self):
        self.cfg['magnets']['length_mm']=20
        self.cfg['spacers']['thickness_mm']=2
        g=sim.derive(self.cfg)
        self.assertEqual(g['period_mm'],44)
        self.assertAlmostEqual(g['pitch_mm'],44/6)
        self.assertEqual(g['magnet_rod_mm'],26*20+25*2)
    def test_automatic_turn_packing(self):
        w=self.cfg['winding'];w.update(layers=0,turns_per_layer=0,max_outer_diameter_mm=20.1)
        g=sim.derive(self.cfg)
        self.assertEqual((g['layers'],g['columns']),(6,12))
    def test_collision_rejected_before_solver(self):
        self.cfg['winding']['turns_per_layer']=13
        with self.assertRaisesRegex(ValueError,'does not fit'):sim.derive(self.cfg)
    def test_unbalanced_parallel_branches_rejected(self):
        self.cfg['winding']['parallel_branches_per_phase']=3
        with self.assertRaisesRegex(ValueError,'Parallel branches'):sim.derive(self.cfg)
    def test_unknown_parameter_rejected(self):
        text=Path(__file__).with_name('motor_parameters.example.ini').read_text(encoding='utf-8')
        text=text.replace('payload_g =','paylod_g =')
        parent=Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory(dir=parent) as folder:
            self.assertTrue(Path(folder).resolve().is_relative_to(parent))
            p=Path(folder)/'p.ini';p.write_text(text,encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'paylod_g'):sim.read_parameters(p)
    def test_decimal_comma_and_list_separator(self):
        self.assertEqual(sim.convert('0,5; 1,25; 2','list'),[.5,1.25,2.])
        self.assertEqual(sim.convert('auto; 40','targets'),['auto',40.])
    def test_three_phase_balance_for_supported_geometries(self):
        for density,pairs in [(3,2),(6,1.5),(6,2),(12,1.5)]:
            c=copy.deepcopy(self.cfg);c['winding'].update(coils_per_pole_pair=density,pole_pairs=pairs,turns_per_layer=0)
            g=sim.derive(c);items=sim.plan(g)
            coeff=sum(a['sense']*cmath.exp(2j*math.pi*a['center_mm']/g['period_mm']) for a in items if a['phase']=='A')
            origin=cmath.phase(coeff);forces=[]
            for i in range(40):
                theta=2*math.pi*i/40
                total=sum(a['sense']*math.cos(theta+2*math.pi*a['center_mm']/g['period_mm'])*math.cos(theta+origin+'ABC'.index(a['phase'])*2*math.pi/3) for a in items)
                forces.append(total)
            self.assertLess(max(forces)-min(forces),1e-10)
    def test_delta_current_is_line_difference(self):
        self.cfg['winding'].update(parallel_branches_per_phase=2,connection='delta')
        currents=[2.,-1.,-1.]
        self.assertEqual(sim.driver_currents(currents,self.cfg),[6.,-6.,0.])

    def test_first_start_creates_local_parameters_once(self):
        parent=Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory(dir=parent) as folder:
            directory=Path(folder)
            example=directory/'motor_parameters.example.ini'
            example.write_text('[winding]\npole_pairs = 1.5\n',encoding='utf-8')
            local=sim.default_parameters(directory)
            self.assertEqual(sim.derive(sim.read_parameters(local))['count'],9)
            local.write_text('[winding]\npole_pairs = 1\n',encoding='utf-8')
            sim.default_parameters(directory)
            self.assertEqual(sim.derive(sim.read_parameters(local))['count'],6)

    def test_explicit_missing_parameters_are_not_silently_replaced(self):
        with self.assertRaisesRegex(ValueError,'not found'):
            sim.read_parameters(Path(__file__).with_name('missing-parameters-for-test.ini'))

    def test_english_cli_selects_headless_quick_test(self):
        example=Path(__file__).with_name('motor_parameters.example.ini')
        with patch.object(sim,'simulate',return_value={}) as solve:
            self.assertEqual(sim.main([str(example),'--headless','--quick-test']),0)
        _,config,quick=solve.call_args.args
        self.assertFalse(config['display']['visible'])
        self.assertTrue(quick)

    def test_supplied_packet_length_examples(self):
        examples=Path(__file__).parent/'examples'
        for name,count,length in [('six_coils.ini',6,42),('nine_coils.ini',9,63)]:
            with self.subTest(example=name):
                geometry=sim.derive(sim.read_parameters(examples/name))
                self.assertEqual(geometry['count'],count)
                self.assertEqual(geometry['packet_mm'],length)

if __name__=='__main__':unittest.main()
