/**
 * D-16 — what the planner reserves must be what the renderer draws.
 *
 * The deviation was one defect wearing three faces (docs/phase5_deviation_
 * register.md, D-16):
 *
 *   (a) the horizontal collision window was the constant LABEL_SEP_PX_X = 64,
 *       while the file's own comment computed 'excavator_01 NAV' at ~86 px —
 *       so two labels 64-86 px apart passed the collision test and overlapped
 *       by up to 22.4 px;
 *   (b) the battery gauge was in no plan at all, so nothing reserved its space
 *       and two robots close together drew indistinguishable superimposed bars;
 *   (c) the colour-blind-safe STATE_ABBREV was drawn only inside
 *       `if (labelPlaced)`, so it vanished exactly when robots cluster.
 *
 * Each face has a test below that fails against the pre-fix code. The last
 * group is the general one: run the real `drawRobots` against a recording
 * context and assert that every mark it emits is inside a box `planRobotMarks`
 * reported, for six synthetic layouts including a ten-robot pile on the depot.
 *
 * WHAT THIS CANNOT DO. It is not a browser. `measureText` here is a monospace
 * model (0.6 em advance, the same figure FleetMap's own comments assume), so it
 * pins that the planner and the renderer use the SAME width for the SAME
 * string — which is the defect — and not that a real JetBrains Mono advance is
 * 0.6 em. It also cannot see colour, antialiasing, the WORKING glow (a
 * shadowBlur, which paints outside every box here and is deliberately not
 * modelled), or whether the result is legible. Nothing in this file was
 * rendered. See NEEDS A LIVE CHECK in the owner report.
 */

import {
  drawRobots,
  orderRobotsForLabels,
  planRobotMarks,
} from '../components/FleetMap';
import {
  boxContains,
  boxesOverlap,
  createRecordingContext,
} from '../testUtils/recordingCanvas';

// The advance the whole suite models. Kept identical everywhere because
// FleetMap caches measured widths by string at module scope, so two tests
// disagreeing about the font would see each other's cached numbers.
const ADVANCE_EM = 0.6;
const LABEL_FONT_PX = 9;

// Width in CSS px of a label string under the model above.
const modelWidth = (text) => ADVANCE_EM * LABEL_FONT_PX * text.length;

function robot(id, x, y, extra = {}) {
  return {
    robot_id: id,
    robot_type: 'excavator',
    fsm_state: 'NAVIGATING',
    pose: { x, y, theta: 0 },
    battery_level: 0.62,
    lastUpdate: 1000,
    ...extra,
  };
}

// `now` close to lastUpdate so isStale() is false and alpha stays 1.
const NOW = 1100;

function asMap(list) {
  const out = {};
  list.forEach((r) => { out[r.robot_id] = r; });
  return out;
}

// drawRobots is called by the render loop from INSIDE the world transform
// (worldToCanvas: translate to the canvas centre, then scale(scale, -scale)).
// The centring translate is dropped here so device coordinates are exactly the
// planner's px space — px_x = worldX * scale, px_y = -worldY * scale — which is
// what makes the containment assertions readable.
function withWorldTransform(ctx, scale, fn) {
  ctx.save();
  ctx.scale(scale, -scale);
  fn();
  ctx.restore();
}

// Run the real renderer against a recording context and hand back both the
// marks it emitted and the plan it drew them from.
function render(robots, { scale = 4.3, selectedRobotId = null } = {}) {
  const ctx = createRecordingContext({ advanceEm: ADVANCE_EM });
  withWorldTransform(ctx, scale, () => {
    drawRobots(ctx, asMap(robots), selectedRobotId, scale, NOW);
  });
  const ordered = orderRobotsForLabels(robots, selectedRobotId);
  ctx.font = `${LABEL_FONT_PX / scale}px JetBrains Mono, monospace`;
  const plans = planRobotMarks(
    ordered, scale, selectedRobotId, (t) => ctx.measureText(t).width * scale,
  );
  return { marks: ctx.marks, plans };
}

// Every box a plan describes, for containment checks.
function planBoxes(plan) {
  const boxes = [plan.iconBox, plan.dotBox];
  if (plan.gaugeBox) boxes.push(plan.gaugeBox);
  if (plan.label) boxes.push(plan.label.box);
  return boxes;
}

// ---------------------------------------------------------------- (a) width

describe('D-16(a): the collision window is the measured label width', () => {
  test('two labels closer than their own width do not both get placed', () => {
    // 'excavator_01 ' + 'NAV' is 16 characters => 86.4 px at 0.6 em / 9 px.
    // The old window was 64 px, so a 70 px separation passed it and the two
    // labels still overlapped by 16.4 px. Here they must not both be placed at
    // the same row.
    const scale = 1;
    const sepPx = 70;
    const plans = planRobotMarks(
      orderRobotsForLabels([robot('excavator_01', 0, 0), robot('excavator_02', sepPx, 0)], null),
      scale,
      null,
      (t) => modelWidth(t),
    );
    const a = plans.get('excavator_01').label;
    const b = plans.get('excavator_02').label;
    expect(a).not.toBeNull();
    expect(b).not.toBeNull();
    expect(modelWidth('excavator_01 NAV')).toBeCloseTo(86.4, 6);
    expect(sepPx).toBeLessThan(modelWidth('excavator_01 NAV'));
    expect(boxesOverlap(a.box, b.box)).toBe(false);
  });

  test('a wider id gets a wider reservation — the window is not a constant', () => {
    const scale = 1;
    const measure = (t) => modelWidth(t);
    const narrow = planRobotMarks(
      orderRobotsForLabels([robot('s1', 0, 0)], null), scale, null, measure,
    ).get('s1').label;
    const wide = planRobotMarks(
      orderRobotsForLabels([robot('excavator_01', 0, 0)], null), scale, null, measure,
    ).get('excavator_01').label;
    expect(narrow.box.x1 - narrow.box.x0).toBeCloseTo(modelWidth('s1 NAV'), 6);
    expect(wide.box.x1 - wide.box.x0).toBeCloseTo(modelWidth('excavator_01 NAV'), 6);
    expect(wide.box.x1 - wide.box.x0).toBeGreaterThan(narrow.box.x1 - narrow.box.x0);
  });

  test('two labels 100 px apart both fit, because 100 > 86.4', () => {
    const plans = planRobotMarks(
      orderRobotsForLabels([robot('excavator_01', 0, 0), robot('excavator_02', 100, 0)], null),
      1, null, (t) => modelWidth(t),
    );
    expect(plans.get('excavator_01').label.tier).toBe('full');
    expect(plans.get('excavator_02').label.tier).toBe('full');
    expect(plans.get('excavator_02').label.topPx)
      .toBeCloseTo(plans.get('excavator_01').label.topPx, 6);
  });
});

// ---------------------------------------------------------------- (b) gauge

describe('D-16(b): the battery gauge is reserved, not just drawn', () => {
  test('every robot reporting a battery level gets a gauge box in the plan', () => {
    const { plans } = render([robot('a', 0, 0), robot('b', 3, 0), robot('c', 6, 0)]);
    ['a', 'b', 'c'].forEach((id) => {
      expect(plans.get(id).gaugeBox).not.toBeNull();
      expect(plans.get(id).gaugeRect).not.toBeNull();
    });
  });

  test('a robot with no battery_level gets no gauge but keeps its label slot', () => {
    const { plans } = render([robot('a', 0, 0, { battery_level: undefined })]);
    expect(plans.get('a').gaugeRect).toBeNull();
    // The label still starts below the slot a gauge would have occupied, so a
    // robot without a reading does not float its label up into the row every
    // other robot's gauge uses.
    const withGauge = render([robot('b', 0, 0)]).plans.get('b');
    expect(plans.get('a').label.topPx).toBeCloseTo(withGauge.label.topPx, 6);
  });

  test('two coincident robots get non-overlapping gauges, and neither is dropped', () => {
    // GAUGE_W_PX is 20 and GAUGE_H_PX is 3: 3 px of separation in x is well
    // inside both, which is exactly the case D-16(b) names.
    const scale = 1;
    const plans = planRobotMarks(
      orderRobotsForLabels([robot('a', 0, 0), robot('b', 3, 0)], null),
      scale, null, (t) => modelWidth(t),
    );
    const ga = plans.get('a').gaugeBox;
    const gb = plans.get('b').gaugeBox;
    expect(ga).not.toBeNull();
    expect(gb).not.toBeNull();
    expect(boxesOverlap(ga, gb)).toBe(false);
    // The later one stepped DOWN. It is still centred under its own icon in x,
    // so it cannot be read as belonging to the other robot.
    expect(plans.get('b').gaugeDy).toBeGreaterThan(0);
    expect((gb.x0 + gb.x1) / 2).toBeCloseTo(3, 6);
  });

  test('no label is ever placed on top of another robot gauge', () => {
    const fleet = [];
    for (let i = 0; i < 8; i += 1) {
      fleet.push(robot(`excavator_0${i}`, (i % 4) * 4, -Math.floor(i / 4) * 3));
    }
    const { plans } = render(fleet, { scale: 4.3 });
    const gauges = [];
    const labels = [];
    plans.forEach((p) => {
      if (p.gaugeBox) gauges.push(p.gaugeBox);
      if (p.label) labels.push(p.label.box);
    });
    labels.forEach((l) => {
      gauges.forEach((g) => {
        expect(boxesOverlap(l, g)).toBe(false);
      });
    });
  });
});

// --------------------------------------------------------------- (c) abbrev

describe('D-16(c): the state abbreviation survives a crowd', () => {
  test('a robot that cannot fit its id still gets its state abbreviation', () => {
    // Ten robots 20 px apart at 1 px/m. 'excavator_0 NAV' is 81 px, so the full
    // row collides for every robot past the fourth and exhausts its three
    // nudges; the bare 3-character row is 16.2 px, well inside 20, so it fits
    // on the first row it is offered. Before D-16(c) every one of these lost
    // its state text entirely.
    const fleet = [];
    for (let i = 0; i < 10; i += 1) {
      fleet.push(robot(`excavator_${i}`, i * 20, 0, {
        fsm_state: ['NAVIGATING', 'WORKING', 'IDLE'][i % 3],
      }));
    }
    const { plans } = render(fleet, { scale: 1 });
    let abbrevTier = 0;
    let dropped = 0;
    plans.forEach((p) => {
      if (!p.label) dropped += 1;
      else if (p.label.tier === 'abbrev') abbrevTier += 1;
    });
    // The point of the fix: the fallback is actually used in a crowd.
    expect(abbrevTier).toBeGreaterThan(0);
    // And it strictly beats the old behaviour, where every one of these would
    // have been dropped outright once the id did not fit.
    expect(dropped).toBeLessThan(fleet.length - 1);
  });

  test('the abbrev tier draws the state text and no id text', () => {
    const fleet = [];
    for (let i = 0; i < 10; i += 1) {
      fleet.push(robot(`excavator_${i}`, i * 20, 0, { fsm_state: 'RECHARGING' }));
    }
    const { marks, plans } = render(fleet, { scale: 1 });
    const abbrevIds = [];
    plans.forEach((p, id) => { if (p.label && p.label.tier === 'abbrev') abbrevIds.push(id); });
    expect(abbrevIds.length).toBeGreaterThan(0);
    const texts = marks.filter((m) => m.kind === 'fillText').map((m) => m.text);
    // 'CHG' appears once per placed row of either tier; no id text is drawn for
    // a robot whose row fell back to the abbrev tier.
    abbrevIds.forEach((id) => {
      expect(texts).not.toContain(`${id} `);
    });
    expect(texts.filter((t) => t === 'CHG').length).toBeGreaterThanOrEqual(abbrevIds.length);
  });

  test('an unknown FSM state still gets a three-character row', () => {
    const { plans } = render([robot('a', 0, 0, { fsm_state: 'NOT_A_STATE' })]);
    expect(plans.get('a').label.abbrev).toBe('???');
  });
});

// -------------------------------------------- the general containment claim

describe('every mark drawn lands inside a box the plan reserved', () => {
  const LAYOUTS = {
    'single robot': [robot('scout_01', 0, 0)],
    'two robots, one label width apart': [
      robot('excavator_01', 0, 0), robot('excavator_02', 20, 0),
    ],
    'a row on the depot': [0, 1, 2, 3].map(
      (i) => robot(`hauler_0${i}`, -30 + i * 2, -100),
    ),
    'ten robots piled on one point': Array.from({ length: 10 }, (_, i) => robot(
      `robot_${i}`, -30 + (i % 3) * 0.4, -100 + Math.floor(i / 3) * 0.4,
      { fsm_state: ['IDLE', 'BIDDING', 'ASSIGNED', 'ERROR', 'RECHARGING'][i % 5] },
    )),
    'a stale robot and an ERROR robot': [
      robot('scout_01', 0, 0, { lastUpdate: 1 }),
      robot('scout_02', 40, 0, { fsm_state: 'ERROR' }),
    ],
    'a robot with no battery reading': [
      robot('scout_01', 0, 0, { battery_level: undefined }),
      robot('scout_02', 8, 0),
    ],
  };

  // MIN_SCALE, the default framing, and MAX_SCALE.
  const SCALES = [0.3, 4.3, 20];

  Object.entries(LAYOUTS).forEach(([name, fleet]) => {
    SCALES.forEach((scale) => {
      test(`${name} @ ${scale} px/m`, () => {
        const selected = fleet.length > 1 ? fleet[1].robot_id : null;
        const { marks, plans } = render(fleet, { scale, selectedRobotId: selected });
        expect(marks.length).toBeGreaterThan(0);
        const boxes = [];
        plans.forEach((p) => boxes.push(...planBoxes(p)));
        marks.forEach((mark) => {
          const inside = boxes.some((b) => boxContains(b, mark.box));
          if (!inside) {
            throw new Error(
              `${mark.kind} ${mark.text || ''} at `
              + `[${mark.box.x0.toFixed(2)}, ${mark.box.y0.toFixed(2)}, `
              + `${mark.box.x1.toFixed(2)}, ${mark.box.y1.toFixed(2)}] `
              + 'is inside no box the plan reserved',
            );
          }
        });
      });
    });
  });

  test('reserved boxes do not overlap, except the two the plan flags as forced', () => {
    // Ten robots spread over 30 m of the depot apron at the default framing:
    // dense enough that some labels are dropped, sparse enough that every
    // gauge can be resolved. Anything the planner could not resolve has to be
    // FLAGGED — that is what makes an unavoidable pile-up distinguishable from
    // a planner that silently gave up.
    const fleet = Array.from({ length: 10 }, (_, i) => robot(
      `robot_${i}`, -40 + (i % 5) * 8, -100 + Math.floor(i / 5) * 8,
    ));
    const { plans } = render(fleet, { scale: 4.3, selectedRobotId: 'robot_3' });
    const reserved = [];
    plans.forEach((p) => {
      if (p.gaugeBox) reserved.push({ box: p.gaugeBox, forced: p.gaugeForced });
      if (p.label) reserved.push({ box: p.label.box, forced: p.label.forced });
    });
    expect(reserved.length).toBeGreaterThan(10);
    let unflaggedOverlaps = 0;
    for (let i = 0; i < reserved.length; i += 1) {
      for (let j = i + 1; j < reserved.length; j += 1) {
        if (reserved[i].forced || reserved[j].forced) continue;
        if (boxesOverlap(reserved[i].box, reserved[j].box)) unflaggedOverlaps += 1;
      }
    }
    expect(unflaggedOverlaps).toBe(0);
  });

  test('a pile-up the planner cannot resolve is reported, not hidden', () => {
    // Five robots inside one gauge width of each other. GAUGE_MAX_ATTEMPTS is
    // 2, so the fourth and fifth cannot be separated. They are still drawn —
    // the gauge is the mark that is never dropped — and gaugeForced says so.
    const fleet = Array.from({ length: 5 }, (_, i) => robot(`pile_${i}`, i * 0.5, 0));
    const { plans } = render(fleet, { scale: 1 });
    const forced = [];
    plans.forEach((p, id) => {
      expect(p.gaugeRect).not.toBeNull();
      if (p.gaugeForced) forced.push(id);
    });
    expect(forced.length).toBeGreaterThan(0);
  });

  test('the plan is stable across frames for an unchanged fleet', () => {
    // The renderer runs at 30 fps against a 2 Hz telemetry feed, so the plan is
    // recomputed ~15 times per input change. A plan that depended on iteration
    // order or on a cache warming up would make labels flicker.
    const fleet = Array.from({ length: 6 }, (_, i) => robot(`hauler_0${i}`, i * 3, 0));
    const first = render(fleet, { scale: 4.3 }).plans;
    const second = render(fleet, { scale: 4.3 }).plans;
    first.forEach((p, id) => {
      expect(second.get(id).label && second.get(id).label.topPx)
        .toEqual(p.label && p.label.topPx);
      expect(second.get(id).gaugeDy).toEqual(p.gaugeDy);
    });
  });
});

// ------------------------------------------------------- measurement budget

describe('measuring the label does not cost a measureText per frame', () => {
  test('a cold cache does measure — so the zero below is not the instrument', () => {
    // An id never seen before must cost at least one measureText. Not an exact
    // count: the nine STATE_ABBREV strings are shared, so whether this robot's
    // abbreviation is already cached depends on what ran before it, and that
    // sharing is the point of keying the cache on the string.
    const ctx = createRecordingContext({ advanceEm: ADVANCE_EM });
    withWorldTransform(ctx, 4.3, () => drawRobots(
      ctx, asMap([robot('coldcache_01', 0, 0)]), null, 4.3, NOW,
    ));
    expect(ctx.measureCalls).toBeGreaterThan(0);
  });

  test('a warmed cache issues no measureText calls at all', () => {
    const fleet = Array.from({ length: 6 }, (_, i) => robot(`budget_${i}`, i * 30, 0));
    const scale = 4.3;
    // Frame 1 warms FleetMap's module-level width cache.
    const warm = createRecordingContext({ advanceEm: ADVANCE_EM });
    withWorldTransform(warm, scale, () => drawRobots(warm, asMap(fleet), null, scale, NOW));

    const ctx = createRecordingContext({ advanceEm: ADVANCE_EM });
    withWorldTransform(ctx, scale, () => drawRobots(ctx, asMap(fleet), null, scale, NOW));
    expect(ctx.measureCalls).toBe(0);
    // and it still drew: an id and a state abbreviation for each of the six.
    expect(ctx.marks.filter((m) => m.kind === 'fillText').length).toBe(12);
  });

  test('a scale change does not invalidate the cache', () => {
    const fleet = [robot('zoomer_01', 0, 0)];
    drawRobots(createRecordingContext({ advanceEm: ADVANCE_EM }),
      asMap(fleet), null, 1, NOW);
    const ctx = createRecordingContext({ advanceEm: ADVANCE_EM });
    withWorldTransform(ctx, 17.5, () => drawRobots(ctx, asMap(fleet), null, 17.5, NOW));
    expect(ctx.measureCalls).toBe(0);
  });
});
