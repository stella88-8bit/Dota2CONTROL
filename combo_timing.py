"""Resource and first-impact scheduling for a stationary, manually aimed target.

The planner never claims knowledge of enemy coordinates, resistance or movement.
It solves timing constraints for the distance explicitly supplied by the user.
"""
from dataclasses import dataclass, field
import itertools
import math

KEY_STEP = .016
INVOKE_SETTLE = .065
CAST_PADDING = .025
LAND_MARGIN = .08
HIT_WINDOW = .4


def collision_flight(distance, speed, radius_start=0, radius_end=None, travel_distance=None):
    """Leading edge of a linear point/cone projectile, point-sized target."""
    if speed <= 0:
        raise ValueError('Projectile speed must be positive')
    slope = 0 if radius_end is None or not travel_distance else (radius_end-radius_start)/travel_distance
    return max(0, (distance-radius_start)/(1+slope)) / speed


def _solve(nodes, edges):
    values = {node: 0.0 for node in nodes}
    for _ in range(len(nodes)):
        changed = False
        for before, after, gap in edges:
            candidate = values[before] + gap
            if candidate > values[after] + 1e-9:
                if after == 'start':
                    return None
                values[after] = candidate
                changed = True
        if not changed:
            return values
    return None  # Positive cycle: these windows cannot coexist.


@dataclass
class TimingPlan:
    order: tuple
    warmup: tuple
    cast_offsets: dict
    invoke_offsets: dict
    profile: dict
    distance: float
    landing: float | None
    latencies: dict
    synchronized: bool
    warnings: list = field(default_factory=list)
    blocked_reason: str | None = None
    source_sha256: str = ''

    def cast_point(self, spell):
        return self.profile['spells'][spell]['values'].get('AbilityCastPoint', 0)

    @property
    def invoke_cooldown(self):
        return max(.05, self.profile['invoke_cooldown'])

    @property
    def nominal_lift(self):
        return self.profile['spells']['tornado']['values'].get('lift_duration')

    def release_at(self, spell, sent, started_at):
        # Re-anchor the remaining windows to the actual Tornado dispatch. Do not
        # retroactively change a Tornado already in flight when orb levels change.
        shift = max([0.0] + [stamp-started_at-self.cast_offsets[name]
                              for name, stamp in sent.items() if name in self.cast_offsets])
        if 'tornado' in sent and 'tornado' in self.cast_offsets:
            shift = sent['tornado'] - started_at - self.cast_offsets['tornado']
        release = started_at + self.cast_offsets[spell] + shift
        if 'tornado' in sent and self.landing is not None:
            landing = sent['tornado'] + self.landing - self.cast_offsets['tornado']
            if spell in self.latencies and spell not in ('tornado','forge spirit','alacrity'):
                release = max(release, landing + LAND_MARGIN - self.latencies[spell])
            if spell == 'cold snap':
                release = max(release, landing + LAND_MARGIN)
        if spell == 'deafening blast':
            for damage_spell in ('emp','sun strike','chaos meteor'):
                if damage_spell in sent:
                    release = max(release, sent[damage_spell] + self.latencies[damage_spell]
                                  + LAND_MARGIN - self.latencies['deafening blast'])
        return release

    def impact_report(self, sent, started_at):
        if 'tornado' not in sent or self.landing is None:
            return {}
        landing = sent['tornado'] + self.landing - self.cast_offsets['tornado']
        return {name: {'impact_after_command_s': self.latencies[name],
                       'relative_to_landing_s': stamp+self.latencies[name]-landing,
                       'within_nominal_window': LAND_MARGIN-.001 <= stamp+self.latencies[name]-landing <= HIT_WINDOW+.001}
                for name, stamp in sent.items() if name in self.latencies and name not in ('tornado','forge spirit','alacrity')}

    def as_dict(self):
        return {'order': self.order, 'warmup': self.warmup, 'hero_level': self.profile['hero_level'],
                'orb_levels': self.profile['levels'], 'target_distance_units': self.distance,
                'invoke_cooldown_s': self.profile['invoke_cooldown'], 'cast_offsets_s': self.cast_offsets,
                'invoke_offsets_s': self.invoke_offsets, 'tornado_landing_s': self.landing,
                'impact_latency_s': self.latencies, 'synchronized': self.synchronized,
                'warnings': self.warnings, 'blocked_reason': self.blocked_reason,
                'source_sha256': self.source_sha256,
                'assumptions': ['stationary point target at supplied distance', 'manual mouse aim',
                                'base lift duration; no unknown enemy modifiers',
                                'no movement forced by cast range, no spell block or immunity']}


def _candidate(order, profile, abilities, distance, warm, strict):
    spells = profile['spells']
    nodes, edges = {'start'}, []
    slots = [abilities.get('ability' + str(i), {}).get('name', '') for i in (3,4)]
    slots = [s.removeprefix('invoker_').replace('_',' ') for s in slots]
    previous_invoke = None
    previous_cast = None
    warmup = tuple(reversed(order[:2])) if warm else ()
    invocation_nodes = {}
    cooldown = max(.05, profile['invoke_cooldown'])
    initial_cd = max(0, abilities.get('ability5', {}).get('cooldown',0))

    def invoke(spell, name, prerequisite, gap):
        nonlocal previous_invoke, slots
        nodes.add(name)
        edges.append((prerequisite, name, gap))
        if previous_invoke:
            edges.append((previous_invoke, name, cooldown))
        else:
            edges.append(('start', name, initial_cd))
        previous_invoke = name
        slots = [spell, slots[0]]
        invocation_nodes[name] = spell
        return name

    last_warm = None
    for number, spell in enumerate(warmup):
        if spell not in slots:
            name = 'warm:' + str(number)
            invoke(spell, name, last_warm or 'start',
                   (INVOKE_SETTLE if last_warm else 0) + 3*KEY_STEP)
            last_warm = name
    for index, spell in enumerate(order):
        cast = 'cast:' + spell
        nodes.add(cast)
        if previous_cast:
            previous_spell = order[index-1]
            gap = spells[previous_spell]['values']['AbilityCastPoint'] + CAST_PADDING
            edges.append((previous_cast, cast, gap))
        else:
            edges.append((last_warm or 'start', cast, INVOKE_SETTLE if last_warm else 0))
        if spell not in slots:
            invoke_name = 'invoke:' + spell
            if previous_cast:
                preparation = spells[order[index-1]]['values']['AbilityCastPoint'] + CAST_PADDING + 3*KEY_STEP
                invoke(spell, invoke_name, previous_cast, preparation)
            else:
                invoke(spell, invoke_name, last_warm or 'start', (INVOKE_SETTLE if last_warm else 0)+3*KEY_STEP)
            edges.append((invoke_name, cast, INVOKE_SETTLE))
        for ability in abilities.values():
            if ability.get('name') == 'invoker_' + spell.replace(' ','_'):
                edges.append(('start', cast, max(0, ability.get('cooldown',0))))
                break
        previous_cast = cast

    latencies = {}
    for spell in order:
        v = spells[spell]['values']
        latency = v['AbilityCastPoint']
        if spell in ('emp','sun strike'):
            latency += v['delay']
        elif spell == 'chaos meteor':
            latency += v['land_time']
        elif spell == 'tornado':
            latency += collision_flight(distance,v['travel_speed'],v['area_of_effect'])
        elif spell == 'deafening blast':
            latency += collision_flight(distance,v['travel_speed'],v['radius_start'],v['radius_end'],v['travel_distance'])
        latencies[spell] = latency
    lift_offset = None
    if 'tornado' in order:
        lift_offset = latencies['tornado'] + spells['tornado']['values']['lift_duration']
        anchor = 'cast:tornado'
        for spell in order:
            if spell in ('tornado','forge spirit','alacrity'):
                continue
            if spell == 'cold snap':
                # Do not even issue the targeted command while the target is airborne.
                edges.append((anchor, 'cast:'+spell, lift_offset+LAND_MARGIN))
            else:
                edges.append((anchor,'cast:'+spell,lift_offset+LAND_MARGIN-latencies[spell]))
            if strict:
                edges.append(('cast:'+spell,anchor,latencies[spell]-lift_offset-HIT_WINDOW))
        if 'deafening blast' in order:
            for damage_spell in ('emp','sun strike','chaos meteor'):
                if damage_spell in order:
                    edges.append(('cast:'+damage_spell,'cast:deafening blast',
                                  latencies[damage_spell]+LAND_MARGIN-latencies['deafening blast']))
        if strict and 'cold snap' in order and 'deafening blast' in order:
            # The cursor must still point at the enemy before Blast moves it.
            edges.append(('cast:cold snap','cast:deafening blast',
                          latencies['cold snap']+LAND_MARGIN-latencies['deafening blast']))
    times = _solve(nodes, edges)
    if times is None:
        return None
    offsets = {spell: times['cast:'+spell] for spell in order}
    landing = offsets['tornado']+lift_offset if lift_offset is not None else None
    return TimingPlan(tuple(order),warmup,offsets,
                      {key: {'spell': invocation_nodes[key], 'time_s': times[key]} for key in invocation_nodes},
                      profile,distance,landing,latencies,strict)


def plan_combo(spells, profile, abilities, distance=600, source_sha256=''):
    if not isinstance(distance,(int,float)) or not math.isfinite(distance) or not 0 <= distance <= 4000:
        raise ValueError('Target distance must be between 0 and 4000 game units')
    unavailable = [s for s in spells if not profile['spells'][s]['available']]
    if unavailable:
        raise ValueError('Не изучены необходимые сферы: ' + ', '.join(unavailable))
    if len(set(spells)) != len(spells):
        raise ValueError('This planner requires distinct combo spells')
    # Put Cold Snap last in Tornado combos: all timed projectiles can be launched
    # before its retry-until-targeted GSI barrier. The cursor remains user-controlled.
    if 'tornado' in spells:
        tail = ('cold snap',) if 'cold snap' in spells else ()
        other = tuple(s for s in spells if s != 'cold snap')
        orders = [order+tail for order in itertools.permutations(other)]
    else:
        orders = [tuple(spells)]
    plans = []
    for strict in (True,False):
        for order in orders:
            for warmup in (False,True):
                candidate = _candidate(order, profile, abilities, distance, warmup, strict)
                if candidate is not None:
                    plans.append(candidate)
        if plans:
            break
    if not plans:
        raise ValueError('Не удалось построить расписание прокаста')
    # Earliest last dispatch, then a smaller impact spread and less preparation.
    def score(plan):
        spread = sum(abs(plan.cast_offsets[s]+plan.latencies[s]-(plan.landing or 0)-.15)
                     for s in plan.order if s not in ('tornado','forge spirit','alacrity')) if plan.landing is not None else 0
        return (round(max(plan.cast_offsets.values()),6), spread, len(plan.invoke_offsets))
    best = min(plans,key=score)
    best.source_sha256 = source_sha256
    if not best.synchronized and best.landing is not None:
        best.warnings.append('В принятой модели не найден общий момент попадания после Tornado при этих уровнях, дистанции и двух ячейках; построен ближайший доступный вариант.')
    if 'tornado' in spells:
        reach = profile['spells']['tornado']['values']['travel_distance'] + profile['spells']['tornado']['values']['area_of_effect']
        if distance > reach:
            best.blocked_reason = 'Цель дальше предельной дальности Tornado'
    for spell in ('chaos meteor','emp','cold snap'):
        if spell in spells:
            cast_range = profile['spells'][spell]['values'].get('AbilityCastRange',0)
            if cast_range and distance > cast_range:
                best.blocked_reason = f'Дистанция {distance:g} больше базовой дальности {spell} ({cast_range:g}); подойди ближе'
    if 'ice wall' in spells:
        values = profile['spells']['ice wall']['values']
        best.warnings.append(f'Ice Wall: нужна ориентация героя; стена создаётся на {values["wall_place_distance"]:g} ед. впереди.')
        if values.get('vector_cast_range',0) > 0:
            best.blocked_reason = 'Улучшенный Ice Wall требует векторного ввода; текущий отправитель клавиш его не поддерживает'
        if max(best.cast_offsets.values()) > best.cast_offsets['ice wall'] + values['duration']:
            best.warnings.append('При текущей перезарядке Invoke последовательность длится дольше самой Ice Wall.')
    return best


def main():
    import argparse
    import json
    from pathlib import Path
    from combos import COMBOS
    from invoker_database import SpellDatabase
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hero-level',type=int,default=30)
    parser.add_argument('--quas',type=int,default=8)
    parser.add_argument('--wex',type=int,default=8)
    parser.add_argument('--exort',type=int,default=9)
    parser.add_argument('--distance',type=float,default=600)
    parser.add_argument('--scepter',type=int,choices=(1,2,3))
    parser.add_argument('--shard',type=int,choices=(1,2,3))
    parser.add_argument('--combo',type=int,choices=range(1,len(COMBOS)+1))
    parser.add_argument('--slots',nargs=2,default=['empty','empty'],help='D and F spell names, with underscores instead of spaces')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    database=SpellDatabase()
    profile=database.resolve(args.hero_level,(args.quas,args.wex,args.exort),
                             scepter_option=args.scepter,shard_option=args.shard)
    abilities={'ability3':{'name':'invoker_'+args.slots[0]},
               'ability4':{'name':'invoker_'+args.slots[1]},'ability5':{'can_cast':True,'cooldown':0}}
    result={}
    for index,(phrase,spells) in enumerate(COMBOS.items(),1):
        if args.combo is not None and args.combo != index:
            continue
        result[phrase]=plan_combo(spells,profile,abilities,args.distance,database.metadata['source_sha256']).as_dict()
    rendered=json.dumps(result,ensure_ascii=False,indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(rendered+'\n')
    print(rendered)


if __name__ == '__main__':
    main()
