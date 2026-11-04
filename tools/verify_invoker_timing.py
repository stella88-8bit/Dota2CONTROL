"""Offline coverage report for the level database and conditional timing solver."""
from contextlib import closing
import itertools
import json
from pathlib import Path
import sqlite3
import time

from dota_magic.combo_timing import plan_combo, LAND_MARGIN, HIT_WINDOW
from dota_magic.combos import COMBOS
from dota_magic.invoker_database import SpellDatabase, DATABASE


def main():
    started=time.monotonic()
    database=SpellDatabase()
    with closing(sqlite3.connect(DATABASE)) as connection:
        counts={name:connection.execute('SELECT count(*) FROM '+name).fetchone()[0]
                for name in ('hero_state','orb_state','spell_profile','all_spell_states')}
        assert counts=={'hero_state':30000,'orb_state':1000,'spell_profile':10000,'all_spell_states':300000}
        assert connection.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    abilities={'ability3':{'name':'empty','cooldown':0},'ability4':{'name':'empty','cooldown':0},
               'ability5':{'can_cast':True,'cooldown':0}}
    statistics={phrase:{'plans':0,'fits_nominal_window':0,'best_effort':0,'warmup':0,
                        'without_tornado_window':0,
                        'blocked':0,'minimum_dispatch_s':None,'maximum_dispatch_s':0}
                for phrase in COMBOS}
    examples={}
    for index,levels in enumerate(itertools.product(range(1,10),repeat=3),1):
        profile=database.profile(30,*levels)
        q,w,e=levels
        values=profile['spells']
        assert abs(values['tornado']['values']['lift_duration']-(1.2+.2*(q-1)))<1e-8
        assert values['tornado']['values']['travel_distance']==1500+300*(w-1)
        assert abs(values['cold snap']['values']['duration']-(3+.4*(q-1)))<1e-8
        assert values['emp']['values']['delay']==2.9
        assert values['sun strike']['values']['delay']==1.7
        assert values['chaos meteor']['values']['land_time']==1.3
        for distance in (300,600,700):
            for phrase,spells in COMBOS.items():
                plan=plan_combo(spells,profile,abilities,distance,database.metadata['source_sha256'])
                assert set(plan.order)==set(spells)
                for a,b in zip(plan.order,plan.order[1:]):
                    assert plan.cast_offsets[b]+1e-8>=plan.cast_offsets[a]+plan.cast_point(a)+.025
                invoke_times=[step['time_s'] for step in plan.invoke_offsets.values()]
                for a,b in zip(invoke_times,invoke_times[1:]):
                    assert b-a+1e-8>=plan.invoke_cooldown
                if plan.synchronized and plan.landing is not None:
                    for spell in plan.order:
                        if spell in ('tornado','forge spirit','alacrity') or (spell == 'cold snap' and plan.order.index(spell) < plan.order.index('tornado')):continue
                        delta=plan.cast_offsets[spell]+plan.latencies[spell]-plan.landing
                        assert LAND_MARGIN-1e-7<=delta<=HIT_WINDOW+1e-7,(phrase,levels,distance,spell,delta)
                info=statistics[phrase]
                info['plans']+=1
                info['fits_nominal_window']+=int(plan.synchronized and plan.landing is not None)
                info['best_effort']+=int(not plan.synchronized and plan.landing is not None)
                info['without_tornado_window']+=int(plan.landing is None)
                info['warmup']+=int(bool(plan.warmup))
                info['blocked']+=int(plan.blocked_reason is not None)
                finish=max(plan.cast_offsets.values())
                info['minimum_dispatch_s']=min(info['minimum_dispatch_s'] or finish,finish)
                info['maximum_dispatch_s']=max(info['maximum_dispatch_s'],finish)
                if plan.warmup and 'warmup_example' not in examples:
                    examples['warmup_example']=plan.as_dict()
                if levels==(8,8,9) and distance==600:
                    examples[phrase]=plan.as_dict()
        if index%150==0:
            print(f'Validated orb triples: {index}/729',flush=True)
    report={'source_sha256':database.metadata['source_sha256'], 'steam_build_id':database.metadata['steam_build_id'],
            'counts':counts,'orb_triples_checked':729,'distances_checked_units':[300,600,700],
            'plans_checked':sum(x['plans'] for x in statistics.values()),'results':statistics,'examples':examples,
            'elapsed_seconds':round(time.monotonic()-started,3),
            'scope':'Static first-impact model for stationary point target, supplied distance, base lift; not measured game hits. Includes mathematical orb tuples that may not be reachable in normal play.'}
    path=Path('outputs/invoker-timing-coverage.json')
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({key:value for key,value in report.items() if key!='examples'},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
