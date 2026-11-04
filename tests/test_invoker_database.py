import json
from contextlib import closing
from pathlib import Path
import sqlite3
import unittest

from integration.keyvalues import parse
from dota_magic.invoker_database import DATABASE, RULES, SpellDatabase


class DatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = SpellDatabase()

    def test_complete_level_grid_and_integrity(self):
        with closing(sqlite3.connect(DATABASE)) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            for table,count in (('hero_state',30000),('orb_state',1000),('spell_profile',10000),('all_spell_states',300000)):
                self.assertEqual(db.execute('SELECT count(*) FROM '+table).fetchone()[0],count)
            self.assertEqual(db.execute('SELECT count(*) FROM hero_state WHERE hero_level=1').fetchone()[0],1000)
            self.assertEqual(db.execute('SELECT count(*) FROM hero_state WHERE hero_level=30').fetchone()[0],1000)
        self.assertEqual(self.db.metadata['source_sha256'],json.loads(RULES.read_text())['source_sha256'])

    def test_reference_values_at_low_and_high_ranks(self):
        low=self.db.profile(1,1,1,1)['spells']
        high=self.db.profile(30,9,9,9)['spells']
        self.assertAlmostEqual(low['tornado']['values']['lift_duration'],1.2)
        self.assertAlmostEqual(high['tornado']['values']['lift_duration'],2.8)
        self.assertEqual(low['tornado']['values']['travel_distance'],1500)
        self.assertEqual(high['tornado']['values']['travel_distance'],3900)
        self.assertEqual(low['cold snap']['values']['duration'],3)
        self.assertEqual(high['cold snap']['values']['duration'],6.2)
        self.assertEqual(high['sun strike']['values']['damage'],575)
        self.assertEqual(high['chaos meteor']['values']['travel_distance'],1725)

    def test_only_the_correct_orb_changes_a_dependent_value(self):
        for q in range(1,10):
            for w,e in ((1,1),(9,1),(1,9),(9,9)):
                v=self.db.profile(30,q,w,e)['spells']['tornado']['values']
                self.assertAlmostEqual(v['lift_duration'],1.2+.2*(q-1))
                self.assertAlmostEqual(v['travel_distance'],1500+300*(w-1))
        for w in range(1,10):
            self.assertEqual(self.db.profile(30,4,w,7)['spells']['emp']['values']['delay'],2.9)

    def test_not_learning_an_orb_marks_spells_unavailable(self):
        p=self.db.profile(3,0,1,1)['spells']
        self.assertFalse(p['tornado']['available'])
        self.assertIsNone(p['tornado']['values']['lift_duration'])
        self.assertTrue(p['emp']['available'])

    def test_talents_and_upgrade_choices(self):
        p=self.db.resolve(30,(4,4,4),talents=('special_bonus_unique_invoker_3','special_bonus_unique_invoker_5','special_bonus_unique_invoker_ice_wall_dps'),scepter_option=1,shard_option=2)['spells']
        self.assertEqual(p['tornado']['values']['AbilityCooldown'],22)
        self.assertEqual(p['alacrity']['values']['bonus_attack_speed'],71)
        self.assertEqual(p['ice wall']['values']['damage_per_second'],98)
        self.assertEqual(p['ice wall']['values']['vector_cast_range'],600)
        self.assertEqual(p['ice wall']['values']['wall_width'],150)
        self.assertEqual(p['emp']['values']['damage_per_mana_pct'],90)
        self.assertEqual(p['emp']['values']['drag_speed'],125)
        p=self.db.resolve(30,(3,4,5),scepter_option=2)['spells']
        self.assertAlmostEqual(p['tornado']['values']['twister_duration'],3.1)
        profile=self.db.resolve(30,(8,8,9),talents=('special_bonus_unique_invoker_13',),scepter_option=3)
        self.assertEqual(profile['orbs']['exort']['values']['bonus_damage_per_instance'],36)
        self.assertEqual(profile['orbs']['exort']['values']['max_level'],9)

    def test_gsi_ninth_level_is_not_added_twice(self):
        hero={'level':30,'aghanims_scepter':True,'talent_1':True}
        abilities={'ability'+str(i):{'name':'invoker_'+name,'level':rank}
                   for i,(name,rank) in enumerate(zip(('quas','wex','exort'),(8,8,9)))}
        p=self.db.from_gsi(hero,abilities)
        self.assertEqual(p['levels'],(8,8,9))
        self.assertEqual(p['scepter_option'],3)
        self.assertEqual(p['spells']['sun strike']['values']['damage'],575)
        self.assertEqual(p['spells']['sun strike']['values']['cataclysm_count'],2)
        self.assertEqual(p['spells']['ice wall']['values']['damage_per_second'],128)

    def test_hero_level_does_not_invent_orb_levels_or_talents(self):
        low=self.db.profile(6,2,2,2)
        high=self.db.profile(30,2,2,2)
        self.assertEqual(low['spells'],high['spells'])
        self.assertEqual(low['invoke_cooldown'],5.2)
        self.assertEqual(self.db.profile(30,8,8,9)['invoke_cooldown'],0)

    def test_invalid_lookup_never_clamps_silently(self):
        self.db.profile(30,1,1,1)  # Invalid bool/float must not hit this cached entry.
        for args in ((0,1,1,1),(31,1,1,1),(30,10,1,1),(30,-1,1,1),(30,True,1,1),(30,1.5,1,1)):
            with self.assertRaises(ValueError):self.db.profile(*args)

    def test_keyvalues_comments_and_escaped_quotes(self):
        text='''// ignore "fake" "99"
        "root" { "url" "https://example.test/a" /* ignore braces { } */
        "nested" {"value" "1 2 3"} "quote" "say \\"yes\\"" }'''
        data=parse(text)['root']
        self.assertEqual(data['url'],'https://example.test/a')
        self.assertEqual(data['nested'],{'value':'1 2 3'})
        self.assertEqual(data['quote'],'say "yes"')
        with self.assertRaises(ValueError):parse('"root" { "value" "1"')


if __name__ == '__main__':unittest.main()
