/**
 * OntologyGraph - 2D force-directed ontology renderer.
 *
 * Powered by ``force-graph`` (HTML5 canvas + d3-force). 2D was chosen
 * over 3D because a small structural ontology (13 nodes / 10 edges)
 * reads better on a flat plane - no occlusion, no perspective
 * foreshortening of labels, no camera fatigue.
 *
 * Behaviour:
 * - Physics settles the graph automatically. Drag any node to reposition.
 * - Hover a node → its neighbours brighten, unrelated edges fade,
 *   directional particles animate along the involved links.
 * - Click a node → pins it as the focus and pans/zooms so it's centred.
 * - Right column: focus card with description, properties, in/out edges.
 *
 * SRP: presentation-only. Data comes from the parent
 * (``/ontology/graph`` fetch); this component owns the canvas lifecycle
 * and interaction state, nothing else. Pure data + geometry + drawing
 * live in sibling modules and get re-exported here so consumers keep
 * importing from `../components/ontology-graph`:
 *   - ontology-graph.types.ts   (OntologyNode / OntologyEdge + palette)
 *   - ontology-graph.layout.ts  (card sizes, anchors, initialFocus)
 *   - ontology-graph.canvas.ts  (drawNodeChip, drawRectEdgeLink, ...)
 *   - ontology-graph.focus.tsx  (right-column focus panel)
 *
 * Lazy load: ``force-graph`` is dynamic-imported so the console main
 * bundle stays small; the runtime only lands when this route opens.
 */

import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import {
  CLUSTERS,
  clusterOf,
  shortCard,
  type GraphLinkDatum,
  type GraphNodeDatum,
  type OntologyEdge,
  type OntologyNode,
} from "./ontology-graph.types";
import {
  CARD_W,
  FRONT_SPRITE_SCALE,
  anchorForIncoming,
  anchorForOutgoing,
  baseSpriteScale,
  cardHeightFor,
  initialFocus,
  nodeH,
  nodeSpriteScale,
  nodeW,
} from "./ontology-graph.layout";
import { drawNodeChip } from "./ontology-graph.canvas";
import { FocusCard } from "./ontology-graph.focus";

// Re-export types so `import { OntologyGraph, OntologyNode, OntologyEdge }
// from "../components/ontology-graph"` stays a stable public surface
// (see console/src/routes/ontology.tsx).
export type { OntologyEdge, OntologyNode } from "./ontology-graph.types";

interface Props {
  readonly nodes: readonly OntologyNode[];
  readonly edges: readonly OntologyEdge[];
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function OntologyGraph({ nodes, edges }: Props) {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const hudRef = useRef<HTMLDivElement | null>(null);
  const instanceRef = useRef<any>(null);
  const hoverIdRef = useRef<string | null>(null);
  // Focus ref mirrors pinnedNode for the imperative update paths
  // (line particles, sprite opacity). It is always the "sticky"
  // click-selected node; hover is layered on top of this.
  const focusIdRef = useRef<string | null>(null);
  const [pinnedNode, setPinnedNode] = useState<string | null>(null);
  const [hoverNode, setHoverNode] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const focusName = pinnedNode ?? initialFocus(nodes, edges);

  const neighbourhoods = useMemo(() => {
    const map = new Map<string, Set<string>>();
    for (const n of nodes) map.set(n.name, new Set([n.name]));
    for (const e of edges) {
      map.get(e.from_type)?.add(e.to_type);
      map.get(e.to_type)?.add(e.from_type);
    }
    return map;
  }, [nodes, edges]);

  const graphData = useMemo(() => {
    // Pre-collect outgoing/incoming lists per node - and track a
    // (source, target, linkName) -> row-index map so links can later
    // anchor to the ROW where their name appears on the card.
    const outMap = new Map<string, string[]>();
    const inMap = new Map<string, string[]>();
    // Keys: "<src>|<name>|<tgt>" -> row index in the source's
    // outgoingLines / target's incomingLines. Self-refs stay in the
    // outgoing/incoming lists so they can be visibly connected by a
    // real 3D loop line rather than an isolated `↷` badge.
    const outIndex = new Map<string, number>();
    const inIndex = new Map<string, number>();
    const selfRefIds = new Set<string>();
    for (const e of edges) {
      if (e.from_type === e.to_type) selfRefIds.add(e.from_type);
      const out = outMap.get(e.from_type) ?? [];
      const oIdx = out.length;
      out.push(`${e.name} → ${e.to_type}`);
      outMap.set(e.from_type, out);
      outIndex.set(`${e.from_type}|${e.name}|${e.to_type}`, oIdx);

      const inn = inMap.get(e.to_type) ?? [];
      const iIdx = inn.length;
      inn.push(`${e.from_type} → ${e.name}`);
      inMap.set(e.to_type, inn);
      inIndex.set(`${e.from_type}|${e.name}|${e.to_type}`, iIdx);
    }
    // All nodes render on ONE front plane at full size. An earlier
    // front/back split pushed the lower-degree cards onto a receding
    // plane where perspective + fog made them look permanently hazy /
    // washed out. A single crisp plane (with only a small per-node z
    // jitter for parallax) keeps every card equally sharp and readable.
    const FRONT_LAYER_COUNT = nodes.length;
    const rankedForLayer = nodes
      .map((n) => ({
        name: n.name,
        deg: (outMap.get(n.name)?.length ?? 0) + (inMap.get(n.name)?.length ?? 0),
      }))
      .sort((a, b) => b.deg - a.deg);
    const frontIds = new Set(
      rankedForLayer.slice(0, FRONT_LAYER_COUNT).map((r) => r.name),
    );

    const gnodes: GraphNodeDatum[] = nodes.map((n) => {
      const c = clusterOf(n.name);
      const outs = outMap.get(n.name) ?? [];
      const ins = inMap.get(n.name) ?? [];
      // Per-node card dimensions so cards can be short or tall.
      const h = cardHeightFor(n.property_count, outs.length, ins.length);
      return {
        id: n.name,
        name: n.name,
        cluster: c,
        color: CLUSTERS[c].hex,
        propertyCount: n.property_count,
        outCount: outs.length,
        inCount: ins.length,
        degree: outs.length + ins.length,
        properties: n.properties,
        outgoingLines: outs,
        incomingLines: ins,
        description: n.description,
        key: n.key,
        _w: CARD_W,
        _h: h,
        layer: frontIds.has(n.name) ? "front" : "back",
        hasSelfRef: selfRefIds.has(n.name),
      } as GraphNodeDatum;
    });
    // Sort so BACK-layer nodes come first in the array (for depth-order
    // sanity if anything ever falls back to painter's algorithm).
    gnodes.sort((a, b) => {
      if (a.layer === b.layer) return 0;
      return a.layer === "back" ? -1 : 1;
    });
    // Build every link INCLUDING self-loops. Self-loops route with a
    // special curve (arcs outside the card's right edge) so they
    // visibly connect the outgoing text row to the incoming text row
    // on the same card - see updateLinkEndpoints.
    const glinks: GraphLinkDatum[] = [];
    for (const e of edges) {
      const c = clusterOf(e.from_type);
      const key = `${e.from_type}|${e.name}|${e.to_type}`;
      glinks.push({
        source: e.from_type,
        target: e.to_type,
        label: `${e.name} ${shortCard(e.cardinality)}`,
        color: CLUSTERS[c].hex,
        isCausal: e.is_causal,
        outgoingIndex: outIndex.get(key) ?? 0,
        incomingIndex: inIndex.get(key) ?? 0,
      });
    }
    return { nodes: gnodes, links: glinks };
  }, [nodes, edges]);

  // Mount 3D graph on first render.
  useEffect(() => {
    if (typeof window === "undefined") return;
    let cancelled = false;
    const mount = mountRef.current;
    if (!mount) return;

    (async () => {
      let ForceGraph3D: any;
      let THREE: any;
      try {
        const [fgMod, threeMod] = await Promise.all([
          import("3d-force-graph"),
          import("three"),
        ]);
        ForceGraph3D = fgMod.default ?? fgMod;
        THREE = threeMod;
      } catch (err) {
        if (!cancelled) {
          setIsLoading(false);
          setLoadError(err instanceof Error ? err.message : String(err));
        }
        return;
      }
      if (cancelled || !mountRef.current) return;

      const theme = document.documentElement.getAttribute("data-theme");
      const isDark = theme === "dark";
      const bgColor = isDark ? "#0f1115" : "#f4f6fa";
      const labelColor = isDark ? "#e6e8ee" : "#1c1e24";
      const mutedColor = isDark ? "#a4abb8" : "#575d69";

      const width = mount.clientWidth || 720;
      const height = mount.clientHeight || 720;

      // ---------------------------------------------------------------
      // Card factory: render each card to an offscreen canvas at
      // hi-DPI so text stays crisp, then map it onto a plane MESH.
      // A mesh (rather than a billboard Sprite) lets a card take a
      // real 3D tilt on hover; the camera is a fixed near-front view,
      // so at rest the plane reads exactly like a flat 2D card.
      // ---------------------------------------------------------------
      const cardSpriteCache = new Map<string, any>();
      const emptyNbhd = new Map<string, Set<string>>();

      // Paint a card's canvas texture. Extracted so the click-focus
      // logic can re-paint the same canvas with a CSS-style blur
      // filter applied when the node is currently unfocused - the
      // blur pushes unrelated cards visually further away and lets
      // the focused subgraph read cleanly.
      function paintCardCanvas(
        node: GraphNodeDatum,
        canvas: HTMLCanvasElement,
        ctx: CanvasRenderingContext2D,
        dpr: number,
        cw: number,
        ch: number,
        blurred: boolean,
      ): void {
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.scale(dpr, dpr);
        // 2D canvas filter - browser applies a real Gaussian blur.
        ctx.filter = blurred ? "blur(2.5px)" : "none";
        const savedX = (node as any).x;
        const savedY = (node as any).y;
        const savedLayer = node.layer;
        // One global light source for the WHOLE board: derive this
        // card's light direction from its world position, so every
        // card's specular points at the same distant light and the
        // reflections line up into one coherent source instead of an
        // identical stamp repeated on every card.
        const wx = (node as any).fx ?? savedX ?? 0;
        const wy = (node as any).fy ?? savedY ?? 0;
        const lvx = -520 - wx;
        const lvy = 660 - wy;
        const llen = Math.hypot(lvx, lvy) || 1;
        // world +Y is up, canvas +y is down -> flip y into canvas space.
        const lightDir = { x: lvx / llen, y: -lvy / llen };
        (node as any).x = cw / 2;
        (node as any).y = ch / 2;
        (node as any).layer = "front";
        // Ontology cards always render as a dark "smoked glass" slab in
        // BOTH themes - dark coloured glass with light text keeps a
        // strong, readable, consistent glass-slide look on a light or
        // dark page (a light-tinted body washed the colour out and hurt
        // text contrast). The scene background still follows the theme;
        // only the cards are pinned to the dark palette.
        drawNodeChip(ctx, node, 1, {
          labelColor: "#eef2f8",
          mutedColor: "#9aa6b6",
          isDark: true,
          hoverId: null,
          neighbourhood: emptyNbhd,
          lightDir,
        });
        (node as any).x = savedX;
        (node as any).y = savedY;
        (node as any).layer = savedLayer;
        ctx.filter = "none";
      }

      // Cover-Flow resting tilt: each card sits angled toward the board
      // centre by its X position (left cards face right, right cards
      // face left, the centre card is flat). Hovering straightens the
      // hovered card to face the viewer.
      const BASE_TILT_MAX = 0.4;    // radians (~23deg) at the far edges
      const BASE_TILT_SPREAD = 300; // world-X where the tilt maxes out
      function baseTiltFor(node: any): number {
        const fx = node?.fx ?? node?.x ?? 0;
        const t = Math.max(-1, Math.min(1, -fx / BASE_TILT_SPREAD));
        return t * BASE_TILT_MAX;
      }

      function makeCardSprite(node: GraphNodeDatum): any {
        const cached = cardSpriteCache.get(node.id);
        if (cached) return cached;
        // dpr=3 renders text 3x internal resolution so it stays crisp
        // at the 3D camera distance without upscale blur.
        const dpr = 3;
        const cw = nodeW(node);
        const ch = nodeH(node);
        const c = document.createElement("canvas");
        c.width = cw * dpr;
        c.height = ch * dpr;
        const ctx = c.getContext("2d");
        if (!ctx) return null;
        paintCardCanvas(node, c, ctx, dpr, cw, ch, false);

        const tex = new THREE.CanvasTexture(c);
        tex.minFilter = THREE.LinearFilter;
        tex.magFilter = THREE.LinearFilter;
        tex.needsUpdate = true;
        // Front-layer cards WRITE depth (they occlude any link arc
        // that dips behind them) and render AFTER lines so they sit
        // on top. Back-layer cards do the OPPOSITE: they don't write
        // depth and render BEFORE lines, so any link touching a back
        // card visibly runs OVER that card - the user asked for the
        // back plane to look like it sits behind the link ribbon.
        const isBackNode = node.layer === "back";
        // Plane MESH (not a billboard Sprite) so the card can take a
        // REAL 3D tilt on hover. The camera is a fixed near-front view,
        // so a plane facing +Z looks identical to the old billboard at
        // rest; DoubleSide keeps it visible if the scene is spun.
        const mat = new THREE.MeshBasicMaterial({
          map: tex,
          transparent: true,
          // Fully opaque so cards read as solid glass panels instead of
          // the washed-out translucent look.
          opacity: 1,
          depthWrite: !isBackNode,
          depthTest: true,
          alphaTest: 0.05,
          side: THREE.DoubleSide,
        });
        const geo = new THREE.PlaneGeometry(1, 1);
        const sprite = new THREE.Mesh(geo, mat);
        sprite.renderOrder = isBackNode ? 0 : 2;
        // Resting Cover-Flow tilt derived from the card's board position.
        const baseTilt = baseTiltFor(node);
        sprite.rotation.y = baseTilt;
        sprite.userData.baseTilt = baseTilt;
        const spriteScale = nodeSpriteScale(node);
        sprite.scale.set(cw * spriteScale, ch * spriteScale, 1);
        sprite.userData.baseScaleX = cw * spriteScale;
        sprite.userData.baseScaleY = ch * spriteScale;
        // Store what paintCardCanvas needs so we can re-paint the
        // texture in-place when focus changes (no sprite recreate).
        sprite.userData.paintCtx = ctx;
        sprite.userData.paintCanvas = c;
        sprite.userData.paintDpr = dpr;
        sprite.userData.paintW = cw;
        sprite.userData.paintH = ch;
        sprite.userData.paintNode = node;
        sprite.userData.paintTex = tex;
        sprite.userData.currentlyBlurred = false;
        cardSpriteCache.set(node.id, sprite);
        return sprite;
      }

      // ---------------------------------------------------------------
      // Click focus: applies the sticky selection state uniformly.
      //   focused node + its neighbours -> full opacity, pulled forward
      //                                    on the z-axis to layer 1
      //   everything else                -> dimmed opacity, pushed back
      //                                    on the z-axis, and blurred
      //                                    via a real canvas Gaussian
      //                                    so the focus subgraph reads
      //                                    cleanly.
      // Hover no longer affects visuals - only click drives focus. The
      // hover state is still used for the pointer cursor.
      // ---------------------------------------------------------------
      // Idle cards are FULLY opaque so the dark glass reads crisp on any
      // page background - a sub-1 base let the light page bleed through
      // and made every card look hazy ("foggy"). Blur + dim only kick in
      // for the unfocused subgraph AFTER the operator clicks a node.
      const SPRITE_BASE_OPACITY = 1.0;
      const SPRITE_FOCUS_OPACITY = 1.0;
      const SPRITE_DIM_OPACITY = 0.32;
      const FOCUS_Z = 24;    // gentle nudge forward (was 60, far enough
      const DIM_Z = -70;     // to occlude its own links at close zoom)
      function applyClickFocus(): void {
        const focusId = focusIdRef.current;
        const nbrs = focusId ? neighbourhoods.get(focusId) : null;
        cardSpriteCache.forEach((sprite, nodeId) => {
          if (!sprite || !sprite.material) return;
          const isInSet =
            !focusId || nodeId === focusId || (nbrs?.has(nodeId) ?? false);
          // Opacity.
          sprite.material.opacity = focusId
            ? (isInSet ? SPRITE_FOCUS_OPACITY : SPRITE_DIM_OPACITY)
            : SPRITE_BASE_OPACITY;
          // Blur: only unfocused-subgraph cards get blurred. Re-paint
          // the same canvas so we do NOT recreate the texture object.
          const wantBlur = !!focusId && !isInSet;
          if (sprite.userData.currentlyBlurred !== wantBlur) {
            paintCardCanvas(
              sprite.userData.paintNode,
              sprite.userData.paintCanvas,
              sprite.userData.paintCtx,
              sprite.userData.paintDpr,
              sprite.userData.paintW,
              sprite.userData.paintH,
              wantBlur,
            );
            sprite.userData.paintTex.needsUpdate = true;
            sprite.userData.currentlyBlurred = wantBlur;
          }
          // Z position animation.
          const node = (graphData.nodes as any[]).find((n) => n.id === nodeId);
          if (node) {
            const orig = originalZ.get(nodeId) ?? 0;
            let target = orig;
            if (focusId) target = isInSet ? FOCUS_Z : DIM_Z;
            animateNodeZ(node, target);
            // Sprite-scale animation: focused cards unify at
            // FRONT_SPRITE_SCALE (layer 1 size) so they visually
            // sit on the same plane; unfocused cards return to
            // their natural layer scale.
            const targetScale = focusId && isInSet
              ? FRONT_SPRITE_SCALE
              : baseSpriteScale(node);
            animateNodeSpriteScale(node, targetScale);
          }
        });
      }

      // ---------------------------------------------------------------
      // Pin every node in a 4x4 grid on the XY plane, then push
      // back-layer nodes to a farther Z. That gives real depth in the
      // scene rather than a fake 2D drop-shadow.
      //
      // Spacing is wide enough (240 units) to accommodate the tallest
      // front-layer card that now shows every property + every link.
      // Cards are ≤ ~280 px which at 0.55 sprite scale = ~154 world
      // units tall - a 240 unit row leaves 86 units of breathing room.
      // ---------------------------------------------------------------
      const cols = 5;
      const rows = 3;
      const spacingX = 155;
      const spacingY = 235;
      // Lift the WHOLE grid into Y+ (offset) so even the bottom row's
      // cards sit above y=0. The camera then frames the grid centre and
      // the bottom of the frame lands near y=0 - it never dips into the
      // empty negative-Y area (the operator asked to keep both cards and
      // camera out of Y-). 13 nodes spread across a wide 5x3 grid using
      // the ample horizontal room; the two empty slots are bottom-far.
      const GRID_Y_OFFSET = 180;
      const GRID_CENTER_Y = ((rows - 1) / 2) * spacingY + GRID_Y_OFFSET;
      // Straight-on FRONT view: aim right at the grid centre so the
      // camera can sit at the SAME height (a horizontal line of sight,
      // no bird's-eye tilt) and all three rows frame symmetrically.
      const CAM_TARGET_Y = GRID_CENTER_Y;
      // Slot order (col,row) filled by the degree-ranked nodes, centre-out.
      // Hubs (highest degree) take the middle row; the low-degree tail
      // (SecurityEvent, Turn, UserPreference, ...) spreads to the wide
      // side columns rather than dropping into a Y- bottom row.
      const spiralOrder: readonly [number, number][] = [
        [2, 1], [1, 1], [3, 1],
        [2, 2], [2, 0],
        [1, 2], [3, 2], [1, 0], [3, 0],
        [0, 1], [4, 1],
        [0, 2], [4, 2],
        [0, 0], [4, 0],
      ];
      const sortedByDegree = [...(graphData.nodes as any[])].sort(
        (a, b) => (b.degree ?? 0) - (a.degree ?? 0),
      );
      // originalZ per node so the click-focus can restore positions
      // when the user clicks the background or hits Reset.
      const originalZ = new Map<string, number>();
      sortedByDegree.forEach((n, i) => {
        const slot = spiralOrder[i] ?? [0, 0];
        const col = slot[0];
        const row = slot[1];
        const x = (col - (cols - 1) / 2) * spacingX;
        const y = row * spacingY + GRID_Y_OFFSET;
        // Small per-node Z jitter so cards on the same layer are not
        // all at IDENTICAL z. Adds parallax when the camera pans -
        // sells the "cards floating in space" feel.
        const zJitter = ((n.name.charCodeAt(0) * 7 + n.name.length * 11) % 40) - 20;
        const z = (n.layer === "front" ? 40 : -140) + zJitter;
        n.x = x; n.y = y; n.z = z;
        n.fx = x; n.fy = y; n.fz = z;
        originalZ.set(n.id, z);
      });

      // ---------------------------------------------------------------
      // Z animation: smoothly slide a node to a target z. Used by
      // applyClickFocus so the connected subgraph animates forward
      // and unrelated cards recede on click.
      // ---------------------------------------------------------------
      const activeZAnims = new Map<string, number>();
      function animateNodeZ(node: any, targetZ: number, duration = 520): void {
        const startZ = node.z ?? targetZ;
        if (Math.abs(startZ - targetZ) < 0.5) {
          node.z = targetZ; node.fz = targetZ;
          return;
        }
        const start = performance.now();
        const prev = activeZAnims.get(node.id);
        if (prev !== undefined) cancelAnimationFrame(prev);
        function tick() {
          const now = performance.now();
          const t = Math.min(1, (now - start) / duration);
          // Ease-out cubic - fast start, gentle finish.
          const e = 1 - Math.pow(1 - t, 3);
          const z = startZ + (targetZ - startZ) * e;
          node.z = z;
          node.fz = z;
          const sprite = cardSpriteCache.get(node.id);
          if (sprite) sprite.position.z = z;
          if (t < 1) {
            activeZAnims.set(node.id, requestAnimationFrame(tick));
          } else {
            activeZAnims.delete(node.id);
          }
        }
        activeZAnims.set(node.id, requestAnimationFrame(tick));
      }

      // ---------------------------------------------------------------
      // Sprite-scale animation: smoothly resize a card's sprite to
      // a target sprite-scale factor. Focused cards animate up to
      // FRONT_SPRITE_SCALE (unifying visual size with layer 1);
      // unfocused ones return to their natural layer-based scale.
      // The scale is also mirrored into ``node._currentSpriteScale``
      // so ``nodeSpriteScale()`` and every link anchor helper track
      // the live sprite size as the animation plays out.
      // ---------------------------------------------------------------
      const activeScaleAnims = new Map<string, number>();
      function animateNodeSpriteScale(
        node: any,
        targetScale: number,
        duration = 520,
      ): void {
        const start = performance.now();
        const startScale =
          typeof node._currentSpriteScale === "number"
            ? node._currentSpriteScale
            : baseSpriteScale(node);
        if (Math.abs(startScale - targetScale) < 0.002) {
          node._currentSpriteScale = targetScale;
          return;
        }
        const sprite = cardSpriteCache.get(node.id);
        const cw = sprite?.userData?.paintW ?? nodeW(node);
        const ch = sprite?.userData?.paintH ?? nodeH(node);
        const prev = activeScaleAnims.get(node.id);
        if (prev !== undefined) cancelAnimationFrame(prev);
        function tick() {
          const now = performance.now();
          const t = Math.min(1, (now - start) / duration);
          const e = 1 - Math.pow(1 - t, 3);
          const s = startScale + (targetScale - startScale) * e;
          node._currentSpriteScale = s;
          if (sprite) sprite.scale.set(cw * s, ch * s, 1);
          if (t < 1) {
            activeScaleAnims.set(node.id, requestAnimationFrame(tick));
          } else {
            activeScaleAnims.delete(node.id);
          }
        }
        activeScaleAnims.set(node.id, requestAnimationFrame(tick));
      }

      // ---------------------------------------------------------------
      // Hover behaviour: cards rest at a Cover-Flow Y-yaw (baseTilt) and
      // the hovered card STRAIGHTENS to face the viewer flat (rotation
      // 0), easing in/out. On mouse-out it eases back to its resting
      // tilt. Cards are plane meshes so this is a genuine 3D rotation.
      // ---------------------------------------------------------------
      let tiltedNodeId: string | null = null;
      let hoverLeaveTimer = 0;
      const tiltAnims = new Map<string, number>();
      function animateSpriteTilt(sprite: any, target: number): void {
        if (!sprite?.rotation) return;
        const startRot = sprite.rotation.y ?? 0;
        if (Math.abs(startRot - target) < 0.0015) {
          sprite.rotation.y = target;
          return;
        }
        const start = performance.now();
        const dur = 190;
        const key = sprite.uuid;
        const prev = tiltAnims.get(key);
        if (prev !== undefined) cancelAnimationFrame(prev);
        function tick() {
          const t = Math.min(1, (performance.now() - start) / dur);
          const e = 1 - Math.pow(1 - t, 3);
          sprite.rotation.y = startRot + (target - startRot) * e;
          if (t < 1) tiltAnims.set(key, requestAnimationFrame(tick));
          else tiltAnims.delete(key);
        }
        tiltAnims.set(key, requestAnimationFrame(tick));
      }
      function commitTilt(nodeId: string | null): void {
        if (nodeId === tiltedNodeId) return;
        // Ease the previously hovered card back to its resting tilt.
        if (tiltedNodeId) {
          const prev = cardSpriteCache.get(tiltedNodeId);
          if (prev) animateSpriteTilt(prev, prev.userData?.baseTilt ?? 0);
        }
        tiltedNodeId = nodeId;
        // Straighten the hovered card so it faces the viewer flat.
        if (nodeId) {
          const sp = cardSpriteCache.get(nodeId);
          if (sp) animateSpriteTilt(sp, 0);
        }
      }
      function applyHoverTilt(nodeId: string | null): void {
        // Debounce hover-LEAVE. Straightening a card can momentarily
        // move its (now-flat) face off the cursor, so force-graph reports
        // a hover miss for a frame; without this the card would flip
        // straight->tilted->straight forever near its left/right edge.
        if (nodeId) {
          if (hoverLeaveTimer) {
            window.clearTimeout(hoverLeaveTimer);
            hoverLeaveTimer = 0;
          }
          commitTilt(nodeId);
        } else if (!hoverLeaveTimer) {
          hoverLeaveTimer = window.setTimeout(() => {
            hoverLeaveTimer = 0;
            commitTilt(null);
          }, 180);
        }
      }

      // ---------------------------------------------------------------
      // Create the 3D graph. Links are drawn with a fully custom
      // THREE object per link so their endpoints can land on the
      // EXACT text row where the link name is written on each card,
      // AND the line body arcs BEHIND the front card plane so it
      // never crosses over card text.
      // ---------------------------------------------------------------
      // Number of vertices along each bezier line (higher = smoother
      // curve; 32 reads as a smooth arc without heavy geometry).
      const LINK_SEGMENTS = 32;

      function updateLinkEndpoints(groupObj: any, link: any): void {
        const src = link.source;
        const tgt = link.target;
        if (typeof src !== "object" || typeof tgt !== "object") return;
        if (src.x === undefined || tgt.x === undefined) return;

        const isSelfLoop = src.id === tgt.id;

        // Pick the edge each end leaves from so the line flows straight
        // at its partner: the source exits the edge that faces the
        // target, and the target receives on the edge that faces the
        // source. Cards in the same column (or a self-loop) both use
        // the left edge, giving a tidy side arc instead of a zero-width
        // vertical overlap.
        const dx = (tgt.x ?? 0) - (src.x ?? 0);
        let srcSide: -1 | 1;
        let tgtSide: -1 | 1;
        if (isSelfLoop || Math.abs(dx) < 1) {
          srcSide = -1;
          tgtSide = -1;
        } else {
          srcSide = dx > 0 ? 1 : -1;
          tgtSide = dx > 0 ? -1 : 1;
        }

        const s = anchorForOutgoing(src, link.outgoingIndex ?? 0, srcSide);
        const e = anchorForIncoming(tgt, link.incomingIndex ?? 0, tgtSide);

        // Deterministic per-link phase from the row indices so re-renders
        // produce the same offsets (no jitter between frames).
        const phase = ((link.outgoingIndex ?? 0) * 37 + (link.incomingIndex ?? 0) * 53) % 100 / 100;

        let midX: number;
        let midYAdj: number;
        let midZ: number;

        if (isSelfLoop) {
          // Both endpoints sit on the card's LEFT edge (same policy
          // as every other link), so the loop arcs OUT to the LEFT
          // of the card and comes back. Each loop uses a UNIQUE bulge
          // + vertical stagger keyed on outgoingIndex so N self-refs
          // on the same card fan out into N clearly-separated arcs
          // instead of piling up on top of one another.
          const scale = nodeSpriteScale(src);
          const cardLeft = (src.x ?? 0) - (nodeW(src) * scale) / 2;
          const loopIdx = link.outgoingIndex ?? 0;
          const bulge = 50 + loopIdx * 32;
          midX = cardLeft - bulge;
          // Stagger midY progressively so subsequent loops sit above
          // or below their siblings, not overlapping horizontally.
          midYAdj = (s.y + e.y) / 2 + (loopIdx - 1) * 14;
          // Loops sit slightly IN FRONT of the card plane so they
          // are not occluded by the card body.
          midZ = (src.z ?? 0) + 20;
        } else {
          // Regular link: midpoint offset in -Z (away from camera /
          // behind the front card plane) so the line arcs BEHIND
          // the cards rather than crossing over them. Each link
          // also gets a small per-link phase offset in Z and Y so
          // parallel-ish links don't stack on top of each other.
          const midXBase = (s.x + e.x) / 2;
          const midYBase = (s.y + e.y) / 2;
          const segLen = Math.hypot(e.x - s.x, e.y - s.y, e.z - s.z);
          const zBow = Math.min(180, 50 + segLen * 0.22) * (0.85 + phase * 0.30);
          midX = midXBase;
          midYAdj = midYBase + (phase - 0.5) * 16;
          midZ = Math.min(s.z, e.z) - zBow;
        }

        const line = groupObj.userData.line;
        if (line && line.geometry) {
          const positions = line.geometry.attributes.position.array as Float32Array;
          // Sample the quadratic bezier B(t) = (1-t)^2*P0 + 2(1-t)t*P1 + t^2*P2
          for (let i = 0; i < LINK_SEGMENTS; i++) {
            const t = i / (LINK_SEGMENTS - 1);
            const u = 1 - t;
            const x = u * u * s.x + 2 * u * t * midX + t * t * e.x;
            const y = u * u * s.y + 2 * u * t * midYAdj + t * t * e.y;
            const z = u * u * s.z + 2 * u * t * midZ + t * t * e.z;
            positions[i * 3] = x;
            positions[i * 3 + 1] = y;
            positions[i * 3 + 2] = z;
          }
          line.geometry.attributes.position.needsUpdate = true;
          line.geometry.computeBoundingSphere();
          // Dashed materials need line-distance attributes recomputed
          // whenever vertex positions change.
          if (groupObj.userData.isSelfLoop) {
            (line as any).computeLineDistances?.();
          }
        }

        // Focus-based emphasis: click-driven only. Links touching the
        // pinned focus stay bright + get particle flow, everything
        // else is HIDDEN outright so the focused subgraph reads on a
        // clean plate. (Previously unrelated links were drawn at
        // opacity 0.08 which still visibly cluttered the scene.)
        const focusId = focusIdRef.current;
        const anyFocus = focusId !== null;
        const involved =
          anyFocus && (src.id === focusId || tgt.id === focusId);
        const cone = groupObj.userData.cone;
        const baseOpacity = groupObj.userData.isSelfLoop
          ? (isDark ? 0.9 : 0.85)
          : (isDark ? 0.6 : 0.55);
        const hotOpacity = 1;
        // Belt-and-suspenders hide: set the group AND every child
        // AND drive material opacity to 0 AND shrink the group to
        // a point. Any one of these should hide the link; combined
        // they defeat whatever pass keeps 3d-force-graph's line
        // remnants visible after focus.
        // Keep EVERY link connected on focus - the focused subgraph
        // brightens and the rest just fades back. Dim links stay
        // clearly visible (not near-zero) so clicking an unrelated /
        // dimmed card never reads as "every connection broke".
        const dimOpacity = isDark ? 0.3 : 0.26;
        groupObj.visible = true;
        groupObj.scale.set(1, 1, 1);
        if (line) {
          line.visible = true;
          if (line.material) {
            line.material.opacity = !anyFocus
              ? baseOpacity
              : involved ? hotOpacity : dimOpacity;
            line.material.transparent = true;
            line.material.needsUpdate = true;
          }
        }
        if (cone) {
          cone.visible = true;
          if (cone.material) {
            cone.material.opacity = !anyFocus
              ? (isDark ? 0.85 : 0.75)
              : involved ? 1 : dimOpacity;
            cone.material.transparent = true;
            cone.material.needsUpdate = true;
          }
        }

        // Arrowhead: place it at the target anchor, oriented along
        // the bezier tangent at t=1 (which is 2*(end - mid) for a
        // quadratic bezier). That way the cone flows naturally into
        // the target card even for tightly-curved arcs.
        if (cone) {
          const tx = 2 * (e.x - midX);
          const ty = 2 * (e.y - midYAdj);
          const tz = 2 * (e.z - midZ);
          const tlen = Math.sqrt(tx * tx + ty * ty + tz * tz) || 1;
          const dir = new THREE.Vector3(tx / tlen, ty / tlen, tz / tlen);
          const backDist = 3;
          cone.position.set(
            e.x - dir.x * backDist,
            e.y - dir.y * backDist,
            e.z - dir.z * backDist,
          );
          const up = new THREE.Vector3(0, 1, 0);
          const quat = new THREE.Quaternion().setFromUnitVectors(up, dir);
          cone.setRotationFromQuaternion(quat);
        }

        // Flowing particles along the bezier: only visible for links
        // touching the currently-focused node, otherwise hidden. Their
        // t-parameter is derived from wall-clock time so the flow is
        // continuous even though nodes are pinned.
        const particles = groupObj.userData.particles as any[] | undefined;
        if (particles && particles.length) {
          if (involved) {
            const nowSec = performance.now() * 0.001;
            const speed = 0.35; // full traversal per ~1/speed seconds
            const count = particles.length;
            for (let i = 0; i < count; i++) {
              const p = particles[i];
              // Phase-offset per particle so they space out along
              // the curve rather than stacking.
              const tp = ((nowSec * speed) + i / count) % 1;
              const up_ = 1 - tp;
              const px = up_ * up_ * s.x + 2 * up_ * tp * midX + tp * tp * e.x;
              const py = up_ * up_ * s.y + 2 * up_ * tp * midYAdj + tp * tp * e.y;
              const pz = up_ * up_ * s.z + 2 * up_ * tp * midZ + tp * tp * e.z;
              p.position.set(px, py, pz);
              p.visible = true;
              if (p.material) p.material.opacity = 0.95;
            }
          } else {
            for (const p of particles) p.visible = false;
          }
        }
      }

      const Graph = ForceGraph3D()(mount)
        .backgroundColor(bgColor)
        .width(width)
        .height(height)
        .graphData(graphData)
        .cooldownTicks(0) // static positions; no visible physics dance
        .nodeThreeObject((n: any) => makeCardSprite(n as GraphNodeDatum))
        .nodeThreeObjectExtend(false)
        .linkThreeObject((link: any) => {
          const group = new THREE.Group();
          // Sample-point line for the bezier arc.
          const lineGeo = new THREE.BufferGeometry();
          lineGeo.setAttribute(
            "position",
            new THREE.BufferAttribute(new Float32Array(LINK_SEGMENTS * 3), 3),
          );
          // Self-loops render as a slightly thicker dashed line so
          // they read as "this card references itself" even when
          // the loop crosses the same space as other links.
          const isSelfLoop = link.source === link.target ||
            (typeof link.source === "object" && typeof link.target === "object" && link.source.id === link.target.id);
          const lineMat = isSelfLoop
            ? new THREE.LineDashedMaterial({
                color: link.color,
                transparent: true,
                opacity: isDark ? 0.9 : 0.85,
                dashSize: 4,
                gapSize: 3,
                depthWrite: false,
                depthTest: true,
              })
            : new THREE.LineBasicMaterial({
                color: link.color,
                transparent: true,
                // Softer opacity so many crossing arcs do not dominate
                // the scene. Hovered links get boosted below.
                opacity: isDark ? 0.5 : 0.4,
                depthWrite: false,
                depthTest: true,
              });
          const line = new THREE.Line(lineGeo, lineMat);
          if (isSelfLoop) line.computeLineDistances?.();
          line.renderOrder = 1; // below sprites (renderOrder 2)
          group.add(line);
          // Cone arrowhead - slightly larger for self-loops so the
          // loop direction reads.
          const coneRadius = isSelfLoop ? 3.2 : 2.6;
          const coneHeight = isSelfLoop ? 8 : 6.5;
          const coneGeo = new THREE.ConeGeometry(coneRadius, coneHeight, 12);
          const coneMat = new THREE.MeshBasicMaterial({
            color: link.color,
            transparent: true,
            opacity: isDark ? 0.9 : 0.85,
            depthWrite: false,
            depthTest: true,
          });
          const cone = new THREE.Mesh(coneGeo, coneMat);
          cone.renderOrder = 1;
          group.add(cone);
          // Custom flowing particles - four small emissive spheres
          // that sample points along the bezier curve every frame.
          // Hidden by default; updateLinkEndpoints turns them on for
          // links touching the currently-focused node.
          const PARTICLE_COUNT = 5;
          // Bigger radius so the flow reads at the current camera
          // distance without the dots vanishing into the arc.
          const particleGeo = new THREE.SphereGeometry(4.5, 12, 10);
          const particles: any[] = [];
          for (let i = 0; i < PARTICLE_COUNT; i++) {
            const pMat = new THREE.MeshBasicMaterial({
              color: link.color,
              transparent: true,
              opacity: 1.0,
              // Particles must render ON TOP of every card + arc, no
              // matter which z plane they happen to be at along the
              // bezier - otherwise they visibly disappear whenever
              // the flow passes behind a card body.
              depthWrite: false,
              depthTest: false,
              blending: THREE.AdditiveBlending,
            });
            const p = new THREE.Mesh(particleGeo, pMat);
            p.visible = false;
            p.renderOrder = 5;
            group.add(p);
            particles.push(p);
          }
          group.userData.line = line;
          group.userData.cone = cone;
          group.userData.isSelfLoop = isSelfLoop;
          group.userData.particles = particles;
          // Do a first placement immediately so the link is visible
          // even before force-graph runs its first tick.
          updateLinkEndpoints(group, link);
          return group;
        })
        .linkThreeObjectExtend(false)
        // Update endpoints every frame (nodes are pinned so this is
        // cheap - just re-writes vertex positions per link).
        .linkPositionUpdate((groupObj: any, _pos: any, link: any) => {
          updateLinkEndpoints(groupObj, link);
          return true;
        })
        // Default arrows are disabled - the cone in our custom group
        // is the ONLY arrow.
        .linkDirectionalArrowLength(0)
        // Built-in directional particles are disabled - they draw
        // straight-line paths between raw node centres and can't
        // follow our custom bezier curves. We spawn our own particle
        // meshes on each linkThreeObject group and sample the bezier
        // per-frame in updateLinkEndpoints so the flow ACTUALLY
        // rides the curve.
        .linkDirectionalParticles(() => 0)
        // Link visibility accessor: 3d-force-graph re-evaluates this
        // on every render, so it is the reliable way to hide the
        // "wrong" links when a focus is pinned. We also mirror the
        // change onto group.visible in updateLinkEndpoints for the
        // rAF-driven animation frames.
        // Links are never hidden - focus only changes their opacity
        // (see updateLinkEndpoints), so connections stay drawn on click.
        .linkVisibility(() => true)
        .enableNodeDrag(true)
        .onNodeHover((n: any) => {
          // Cursor feedback + a slight rightward tilt on the hovered
          // card for a tactile, physical glass-card response.
          document.body.style.cursor = n ? "pointer" : "default";
          applyHoverTilt(n?.id ?? null);
        })
        .onNodeClick((n: any) => {
          // Sticky click focus with toggle: clicking the already-
          // focused card clears the focus. Because the cards fill the
          // viewport, an empty-background click is nearly unhittable,
          // so this toggle is the reliable "deselect" path (otherwise
          // a stray click lands on a dimmed card and re-focuses it,
          // which read as "all the links broke").
          const next = focusIdRef.current === n.id ? null : n.id;
          setPinnedNode(next);
          focusIdRef.current = next;
          applyClickFocus();
          refreshLinkParticles();
        })
        .onBackgroundClick(() => {
          setPinnedNode(null);
          focusIdRef.current = null;
          applyClickFocus();
          refreshLinkParticles();
        })
        .onNodeDragEnd((n: any) => {
          n.fx = n.x; n.fy = n.y; n.fz = n.z;
        });

      // ---------------------------------------------------------------
      // refreshLinkParticles rewires 3d-force-graph's linkVisibility
      // accessor. Setting an accessor to a fresh function is the
      // canonical way to force 3d-force-graph to re-evaluate visibility
      // on every link the next time it renders (its internal cache
      // keys off the accessor reference identity). We also nudge the
      // renderer/simulation so the change is applied immediately.
      // ---------------------------------------------------------------
      function refreshLinkParticles(): void {
        // Update 3d-force-graph's linkVisibility accessor. Setting it
        // to a new function reference makes force-graph re-evaluate
        // link visibility on the next tick / render.
        try {
          Graph.linkVisibility(() => true);
        } catch {
          /* ignore */
        }
        // Walk every rendered link right now and force its visibility
        // state to match. This is the reliable path when force-graph
        // has already paused its animation loop (cooldownTicks(0)):
        //   - .visible flag stops the traversal in the renderer
        //   - .scale.set(0,0,0) collapses geometry to a single point
        //     so even a rogue render path draws nothing
        //   - opacity 0 on materials as a third safety net
        const data = Graph.graphData?.();
        const links = data?.links;
        if (links && Array.isArray(links)) {
          for (const link of links) {
            const grp = (link as any).__threeObj;
            if (!grp) continue;
            grp.visible = true;
            grp.scale.set(1, 1, 1);
          }
        }
        try {
          Graph.resumeAnimation?.();
        } catch {
          /* ignore */
        }
        try {
          const r = Graph.renderer?.();
          const s = Graph.scene?.();
          const c = Graph.camera?.();
          if (r && s && c) r.render(s, c);
        } catch {
          /* ignore */
        }
      }

      // ---------------------------------------------------------------
      // Scene decorations: floor grid, back-wall grid, atmospheric
      // fog, and ambient lighting. Fog gives real perspective depth -
      // objects farther from the camera fade toward the background
      // colour so back-layer cards feel truly "far".
      // ---------------------------------------------------------------
      const scene = Graph.scene();

      // Very light exponential fog. Density kept low (was 0.0007, which
      // washed the back-layer cards toward the pale page colour and made
      // them look foggy) - just enough atmosphere to hint depth while
      // every card's text stays crisp. Depth is carried mainly by the
      // back cards' smaller scale and the floor/wall grids, not fog.
      scene.fog = new THREE.FogExp2(bgColor, 0.0002);

      const floorMajor = isDark ? 0x4f9df5 : 0x5a80c0;
      const floorMinor = isDark ? 0x2a3040 : 0xc8d0e0;
      const floor = new THREE.GridHelper(1400, 28, floorMajor, floorMinor);
      floor.position.y = -260;
      (floor.material as any).transparent = true;
      (floor.material as any).opacity = isDark ? 0.35 : 0.30;
      scene.add(floor);

      // Back wall grid, rotated 90deg so it sits vertically far
      // behind the back-layer cards. Reinforces the z-depth.
      const wall = new THREE.GridHelper(1400, 20, floorMajor, floorMinor);
      wall.rotation.x = Math.PI / 2;
      wall.position.z = -320;
      (wall.material as any).transparent = true;
      (wall.material as any).opacity = isDark ? 0.20 : 0.16;
      scene.add(wall);

      const ambient = new THREE.AmbientLight(0xffffff, 0.85);
      scene.add(ambient);
      const dir = new THREE.DirectionalLight(0xffffff, 0.35);
      dir.position.set(120, 200, 220);
      scene.add(dir);

      // ---------------------------------------------------------------
      // Camera + controls: fixed front view (rotate disabled), so the
      // cards always face the viewer square-on. Users can still zoom
      // and pan the scene. The camera sits far enough back that both
      // depth planes are comfortably visible.
      // ---------------------------------------------------------------
      // ---------------------------------------------------------------
      // Camera + controls: OrbitControls handles pan (LEFT drag) and
      // zoom (wheel). Rotation is a custom middle-mouse handler that
      // rotates around the world Y axis ONLY - OrbitControls' native
      // rotation covers both axes even when polar is clamped, so we
      // bypass it entirely to guarantee horizontal-only spin.
      // ---------------------------------------------------------------
      // Resting view = the straight-on 2x framing; Reset returns here.
      const INITIAL_CAM: [number, number, number] = [0, CAM_TARGET_Y, 540];
      // The intro starts wider (whole graph in view) and glides in to
      // the resting 2x view for a subtle "zoom-in on load" reveal.
      const INTRO_CAM: [number, number, number] = [0, CAM_TARGET_Y, 900];
      Graph.cameraPosition(
        { x: INTRO_CAM[0], y: INTRO_CAM[1], z: INTRO_CAM[2] },
        { x: 0, y: CAM_TARGET_Y, z: 0 },
        0,
      );
      let mouseDragCleanup: (() => void) | null = null;
      try {
        const ctrls: any = Graph.controls?.();
        if (ctrls) {
          // OrbitControls rotation is fully disabled - our custom
          // handler below owns middle-click rotation and enforces
          // horizontal-only motion.
          ctrls.enableRotate = false;
          ctrls.zoomSpeed = 0.35;
          // Pan (LEFT drag on the background) felt too fast: with
          // world-space panning the motion scales with the camera
          // distance (z ~ 780), so a small drag flung the scene.
          // screenSpacePanning maps the drag to the view plane instead,
          // and a low panSpeed keeps it calm and controllable.
          ctrls.screenSpacePanning = true;
          ctrls.panSpeed = 0.1;
          if ((THREE as any).MOUSE) {
            ctrls.mouseButtons = {
              LEFT: (THREE as any).MOUSE.PAN,
              MIDDLE: -1, // OrbitControls sees no button here
              RIGHT: (THREE as any).MOUSE.PAN,
            };
          }
          ctrls.update?.();
        }

        // Custom middle-mouse drag = azimuth-only rotation.
        // We rotate the camera position around the current
        // OrbitControls target using a plain Y-axis rotation matrix.
        // Camera Y stays fixed, so pitch never changes.
        let midActive = false;
        let lastX = 0;
        const cam = Graph.camera?.();
        const target = ctrls?.target;
        // Bottom-right HUD: zoom multiplier (relative to the initial
        // camera distance) + live camera coordinates. Updated straight
        // on the DOM node from the OrbitControls 'change' event so it
        // never triggers a React re-render on every wheel tick.
        // Fixed 1x reference distance so the zoom multiplier is an
        // ABSOLUTE magnification (2x really is twice as close), not a
        // value re-anchored to whatever the current default happens to
        // be. The default camera sits at ~this distance, so it reads 1x;
        // scrolling in raises it (2x, 4x, ...), out lowers it.
        const ZOOM_BASE_DISTANCE = 1080;
        const updateHud = (): void => {
          if (!cam || !target || !hudRef.current) return;
          const ddx = cam.position.x - target.x;
          const ddy = cam.position.y - target.y;
          const ddz = cam.position.z - target.z;
          const dist = Math.hypot(ddx, ddy, ddz) || 1;
          const zoom = ZOOM_BASE_DISTANCE / dist;
          hudRef.current.textContent =
            `zoom ${zoom.toFixed(2)}x   cam ${cam.position.x.toFixed(0)}, ` +
            `${cam.position.y.toFixed(0)}, ${cam.position.z.toFixed(0)}`;
        };
        ctrls?.addEventListener?.("change", updateHud);
        updateHud();
        // Load reveal: glide from the wide intro framing to the resting
        // 2x view shortly after mount, driving the HUD through the tween.
        window.setTimeout(() => {
          Graph.cameraPosition(
            { x: INITIAL_CAM[0], y: INITIAL_CAM[1], z: INITIAL_CAM[2] },
            { x: 0, y: CAM_TARGET_Y, z: 0 },
            470,
          );
          const introStart = performance.now();
          const introTick = () => {
            updateHud();
            if (performance.now() - introStart < 560) {
              requestAnimationFrame(introTick);
            }
          };
          requestAnimationFrame(introTick);
        }, 350);
        const onMouseDown = (ev: MouseEvent) => {
          if (ev.button !== 1) return; // middle only
          midActive = true;
          lastX = ev.clientX;
          ev.preventDefault();
        };
        const onMouseMove = (ev: MouseEvent) => {
          if (!midActive || !cam || !target) return;
          const dx = ev.clientX - lastX;
          lastX = ev.clientX;
          // Sensitivity chosen so a full drag across the canvas
          // rotates roughly a quarter turn.
          const angle = -dx * 0.006;
          const cos = Math.cos(angle);
          const sin = Math.sin(angle);
          const ox = cam.position.x - target.x;
          const oz = cam.position.z - target.z;
          const nx = ox * cos - oz * sin;
          const nz = ox * sin + oz * cos;
          cam.position.x = target.x + nx;
          cam.position.z = target.z + nz;
          // Y stays untouched - guarantees no pitch change.
          cam.lookAt(target);
          ctrls?.update?.();
          updateHud();
        };
        const onMouseUp = (ev: MouseEvent) => {
          if (ev.button === 1) midActive = false;
        };
        mount.addEventListener("mousedown", onMouseDown);
        window.addEventListener("mousemove", onMouseMove);
        window.addEventListener("mouseup", onMouseUp);
        // Prevent the browser scroll cursor on middle click.
        const onAuxDown = (ev: MouseEvent) => {
          if (ev.button === 1) ev.preventDefault();
        };
        mount.addEventListener("auxclick", onAuxDown);
        mouseDragCleanup = () => {
          mount.removeEventListener("mousedown", onMouseDown);
          window.removeEventListener("mousemove", onMouseMove);
          window.removeEventListener("mouseup", onMouseUp);
          mount.removeEventListener("auxclick", onAuxDown);
          ctrls?.removeEventListener?.("change", updateHud);
        };
      } catch {
        /* ignore */
      }
      // Stash the cleanup on the Graph so the effect teardown finds it.
      (Graph as any).__customDrag = mouseDragCleanup;

      // ---------------------------------------------------------------
      // Reset helper: exposed on Graph so the top-right reset button
      // can bring the scene back to its initial state.
      // ---------------------------------------------------------------
      function resetView(): void {
        try {
          Graph.cameraPosition(
            { x: INITIAL_CAM[0], y: INITIAL_CAM[1], z: INITIAL_CAM[2] },
            { x: 0, y: CAM_TARGET_Y, z: 0 },
            600,
          );
        } catch {
          /* ignore */
        }
        // Clear BOTH hover and pin state - hover may have been set on
        // a card that the user was over when they clicked reset.
        hoverIdRef.current = null;
        focusIdRef.current = null;
        setPinnedNode(null);
        setHoverNode(null);
        applyClickFocus();
        refreshLinkParticles();
      }
      (Graph as any).__resetView = resetView;

      instanceRef.current = Graph;
      setIsLoading(false);

      // Resize with container.
      const ro = new ResizeObserver(() => {
        if (!mountRef.current || !instanceRef.current) return;
        instanceRef.current
          .width(mountRef.current.clientWidth || 720)
          .height(mountRef.current.clientHeight || 720);
      });
      ro.observe(mount);
      (Graph as any).__ro = ro;

      // ---------------------------------------------------------------
      // Frame loop for the flowing particles + link geometry. When a
      // focus is active, particles need per-frame position updates AND
      // a fresh render call (3d-force-graph pauses its internal loop
      // once physics cools, so the WebGL renderer will not redraw the
      // moving particles otherwise). ``settlingFrames`` keeps the loop
      // alive for a beat after focus clears so the return animation
      // still shows.
      // ---------------------------------------------------------------
      let animFrameId = 0;
      const renderer3d = Graph.renderer?.();
      const sceneRef = Graph.scene?.();
      const cameraRef = Graph.camera?.();
      function animateFrame() {
        // Always sync every link's visibility + endpoint state from
        // the current focus, so a stale "hidden" state cannot linger
        // after focus clears and vice versa. Physics is pinned so
        // this is cheap - just a per-link update + one render.
        const data = Graph.graphData?.();
        const links = data?.links;
        if (links && Array.isArray(links)) {
          for (const link of links) {
            const grp = (link as any).__threeObj;
            if (grp) updateLinkEndpoints(grp, link);
          }
        }
        if (renderer3d && sceneRef && cameraRef) {
          renderer3d.render(sceneRef, cameraRef);
        }
        animFrameId = requestAnimationFrame(animateFrame);
      }
      animFrameId = requestAnimationFrame(animateFrame);
      (Graph as any).__animFrame = () => cancelAnimationFrame(animFrameId);
    })();

    return () => {
      cancelled = true;
      const fg = instanceRef.current;
      if (fg) {
        try {
          (fg as any).__ro?.disconnect();
          (fg as any).__customDrag?.();
          (fg as any).__animFrame?.();
          fg.pauseAnimation?.();
          fg._destructor?.();
        } catch {
          /* ignore */
        }
        instanceRef.current = null;
      }
      if (mount) mount.innerHTML = "";
      document.body.style.cursor = "default";
    };
  }, [graphData]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleReset = () => {
    const fg = instanceRef.current;
    if (fg && typeof (fg as any).__resetView === "function") {
      (fg as any).__resetView();
    }
  };

  return (
    <div class="ontology-orbit">
      <div class="ontology-orbit-canvas-wrap">
        <div class="ontology-orbit-stage">
        <div ref={mountRef} class="ontology-webgl-mount" />
        {isLoading ? (
          <div class="ontology-webgl-overlay">
            <span class="state-spinner" aria-hidden="true" />
            <span class="muted">Loading 3D graph...</span>
          </div>
        ) : null}
        {loadError ? (
          <div class="ontology-webgl-overlay ontology-webgl-error">
            <span>3D renderer failed to load: {loadError}</span>
          </div>
        ) : null}
        {!isLoading && !loadError ? (
          <button
            type="button"
            class="ontology-orbit-reset"
            onClick={handleReset}
            aria-label="Reset view"
            title="Reset view (clear focus + recenter camera)"
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
              aria-hidden="true"
            >
              <path d="M3 12a9 9 0 0 1 15.5-6.36" />
              <path d="M21 4v6h-6" />
              <path d="M21 12a9 9 0 0 1-15.5 6.36" />
              <path d="M3 20v-6h6" />
            </svg>
            <span>Reset</span>
          </button>
        ) : null}
          <div ref={hudRef} class="ontology-orbit-hud" aria-hidden="true" />
        </div>
        <div class="ontology-orbit-legend" aria-hidden="true">
          {Object.values(CLUSTERS)
            .filter(
              (c) =>
                c.id !== "other" ||
                nodes.some((n) => clusterOf(n.name) === "other"),
            )
            .map((c) => (
              <span key={c.id} class="ontology-orbit-legend-item">
                <span
                  class="ontology-orbit-legend-dot"
                  style={`background: ${c.hex};`}
                />
                {c.label}
              </span>
            ))}
          <span class="ontology-orbit-legend-note">
            drag to pan · middle-click drag to rotate · scroll to zoom · click a card to focus
          </span>
        </div>
      </div>

      <FocusCard
        name={focusName}
        nodes={nodes}
        edges={edges}
        neighbourhood={neighbourhoods.get(focusName) ?? new Set()}
      />
    </div>
  );
}

