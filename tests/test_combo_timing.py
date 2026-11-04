import copy
import unittest

from combos import COMBOS
from combo_timing import plan_combo, collision_flight, LAND_MARGIN, HIT_WINDOW
from invoker_database import SpellDatabase
from predictive_combo import PredictiveComboRunner


def abilities(levels=(8,8,9)):
    return {**{'ability'+str(i):{'name':'invoker_'+name,'level':rank}
               for i,(name,rank) in enumerate(zip(('quas','wex','exort'),levels))},
            'ability3':{'name':'empty','can_cast':True,'cooldown':0},
            'ability4':{'name':'empty','can_cast':True,'cooldown':0},
            'ability5':{'name':'invoker_invoke','can_cast':True,'cooldown':0}}


class TimingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.db=SpellDatabase()

    def test_projectile_leading_edge_geometry(self):
        self.assertAlmostEqual(collision_flight(600,1000,200),.4)
        self.assertAlmostEqual(collision_flight(600,1100,175,225,1000),425/1.05/1100)
        self.assertEqual(collision_flight(100,1000,200),0)

    def test_high_rank_first_impacts_fit_after_landing(self):
        for levels in ((7,7,7),(8,8,9)):
            for name,spells in COMBOS.items():
                p=plan_combo(spells,self.db.profile(30,*levels),abilities(levels),600)
                self.assertTrue(p.synchronized,name)
                if p.landing is None:continue
                for spell in p.order:
                    if spell in ('tornado','forge spirit','alacrity'):continue
                    impact=p.cast_offsets[spell]+p.latencies[spell]
                    self.assertGreaterEqual(impact-p.landing,LAND_MARGIN-1e-8)
                    self.assertLessEqual(impact-p.landing,HIT_WINDOW+1e-8)
                if 'deafening blast' in p.order:
                    blast=p.cast_offsets['deafening blast']+p.latencies['deafening blast']
                    for damage in ('emp','sun strike','chaos meteor'):
                        if damage in p.order:
                            self.assertGreaterEqual(blast,p.cast_offsets[damage]+p.latencies[damage]+LAND_MARGIN-1e-8)
                if 'cold snap' in spells:
                    self.assertEqual(p.order[-1],'cold snap')
                    self.assertGreaterEqual(p.cast_offsets['cold snap'],p.landing+LAND_MARGIN-1e-8)

    def test_low_quas_two_spell_combo_can_charge_emp_before_tornado(self):
        p=plan_combo(('tornado','emp'),self.db.profile(6,1,1,1),abilities((1,1,1)),600)
        self.assertTrue(p.synchronized)
        self.assertEqual(p.order,('emp','tornado'))
        self.assertGreaterEqual(p.cast_offsets['emp']+p.latencies['emp'],p.landing+LAND_MARGIN-1e-8)
        self.assertAlmostEqual(p.profile['spells']['tornado']['values']['lift_duration'],1.2)

    def test_infeasible_low_rank_full_combo_is_not_called_synchronized(self):
        p=plan_combo(COMBOS['мама я миракл'],self.db.profile(3,1,1,1),abilities((1,1,1)),600)
        self.assertFalse(p.synchronized)
        self.assertTrue(p.warnings)

    def test_distance_changes_schedule_and_range_can_block(self):
        profile=self.db.profile(30,8,8,9)
        close=plan_combo(COMBOS['мама я миракл'],profile,abilities(),300)
        far=plan_combo(COMBOS['мама я миракл'],profile,abilities(),650)
        self.assertNotEqual(close.landing,far.landing)
        self.assertIsNotNone(plan_combo(COMBOS['мама я миракл'],profile,abilities(),800).blocked_reason)
        for bad in (float('nan'),-1,5000):
            with self.assertRaises(ValueError):plan_combo(COMBOS['мама я миракл'],profile,abilities(),bad)

    def test_vector_wall_is_not_sent_as_a_normal_key_cast(self):
        profile=self.db.resolve(30,(8,8,8),scepter_option=1)
        p=plan_combo(COMBOS['от меня не убежишь'],profile,abilities(),600)
        self.assertIn('векторного',p.blocked_reason)

    def test_unlearned_orb_rejects_schedule(self):
        with self.assertRaises(ValueError):
            plan_combo(COMBOS['мама я миракл'],self.db.profile(3,0,1,1),abilities((0,1,1)))

    def test_late_actual_tornado_reanchors_remaining_effects(self):
        p=plan_combo(COMBOS['мама я миракл'],self.db.profile(30,8,8,9),abilities(),600)
        actual=10+p.cast_offsets['tornado']+.2
        release=p.release_at('chaos meteor',{'tornado':actual},10)
        landing=actual+p.landing-p.cast_offsets['tornado']
        self.assertGreaterEqual(release+p.latencies['chaos meteor'],landing+LAND_MARGIN-1e-8)
        self.assertGreaterEqual(release,10+p.cast_offsets['chaos meteor']+.2-1e-8)

    def test_runtime_warmup_and_timing_under_delayed_gsi(self):
        for phrase,spells in COMBOS.items():
            levels=(8,8,9)
            data=abilities(levels)
            plan=plan_combo(spells,self.db.profile(30,*levels),data,600)
            run=PredictiveComboRunner(plan.order,0,timing=plan)
            pending=[]; snapshot=copy.deepcopy(data); packet_at=0; orbs=[]
            casts=[]; invokes=[]; invoke_ready=0
            now=0
            while now<15 and not run.complete and not run.error:
                while pending and pending[0][0]<=now:
                    packet_at,snapshot=pending.pop(0)
                action=run.step(now,snapshot,packet_at)
                if action:
                    key,self_target=action
                    if key in 'qwe':orbs.append(key)
                    elif key=='r':
                        self.assertGreaterEqual(now+1e-8,invoke_ready)
                        from combo_runner import ORBS
                        spell=next(name for name,combo in ORBS.items() if combo==''.join(orbs[-3:]))
                        data['ability4']=copy.deepcopy(data['ability3'])
                        data['ability3']={'name':'invoker_'+spell.replace(' ','_'),'can_cast':True,'cooldown':0}
                        invoke_ready=now+plan.invoke_cooldown
                        invokes.append((now,spell))
                    else:
                        ability=data['ability3' if key=='d' else 'ability4']
                        if ability.get('can_cast') is True:
                            spell=ability['name'][8:].replace('_',' ')
                            casts.append((now,spell,self_target))
                            ability.update(can_cast=False,cooldown=20)
                    remaining=max(0,invoke_ready-now)
                    data['ability5'].update(can_cast=remaining==0,cooldown=remaining)
                    pending.append((now+1,copy.deepcopy(data)))
                now=round(now+.005,4)
            self.assertIsNone(run.error,phrase)
            self.assertTrue(run.complete,phrase)
            self.assertEqual([(s,t) for _,s,t in casts],[(s,s=='alacrity') for s in plan.order])
            self.assertAlmostEqual(run.dispatch_complete_at,casts[-1][0])
            if plan.landing is not None:
                impacts=plan.impact_report({s:t for t,s,_ in casts},0)
                for spell,report in impacts.items():
                    self.assertTrue(report['within_nominal_window'],(phrase,spell,report))
            if plan.warmup:
                self.assertGreaterEqual(len(invokes),2)
                self.assertGreaterEqual(casts[0][0],invokes[1][0]+.065-1e-8)

    def test_warmup_prepares_both_spells_before_first_attack(self):
        data=abilities((1,1,1))
        plan=plan_combo(COMBOS['мой любимый 2007 й'],self.db.profile(30,1,1,1),data,300)
        self.assertTrue(plan.warmup)
        run=PredictiveComboRunner(plan.order,0,timing=plan)
        orbs=[];invokes=[];casts=[];now=0
        from combo_runner import ORBS
        while now<10 and len(casts)<2:
            action=run.step(now,data,now)
            if action:
                key,_=action
                if key in 'qwe':orbs.append(key)
                elif key=='r':
                    spell=next(name for name,sequence in ORBS.items() if sequence==''.join(orbs[-3:]))
                    invokes.append((now,spell))
                    data['ability4']=copy.deepcopy(data['ability3'])
                    data['ability3']={'name':'invoker_'+spell.replace(' ','_'),'can_cast':True,'cooldown':0}
                else:
                    self.assertGreaterEqual(len(invokes),2)
                    spell=data['ability3' if key=='d' else 'ability4']['name'][8:].replace('_',' ')
                    casts.append(spell)
                    data['ability3' if key=='d' else 'ability4'].update(can_cast=False,cooldown=20)
                if invokes:
                    remaining=max(0,invokes[-1][0]+plan.invoke_cooldown-now)
                    data['ability5'].update(can_cast=remaining==0,cooldown=remaining)
            now=round(now+.005,4)
        self.assertEqual(casts,list(plan.order[:2]))


if __name__ == '__main__':unittest.main()
