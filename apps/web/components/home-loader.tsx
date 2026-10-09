"use client";

/**
 * Motivation vs Logic
 * Motivation: On a first load the meeting rows come from the browser copy with no names or
 * status yet. A list of "Untitled meeting / Unknown" reads as broken, so the catalog waits
 * behind a live 3D orbit that shows how many meetings have been checked.
 * Logic: One rig of rings and satellites, built once per mount. Satellites light up in step
 * with done / total. Pointer tilts the rig and a drag spins it. Reduced motion stops the
 * auto-spin and the orbits but keeps pointer control.
 */
import { useEffect, useRef } from "react";
import * as THREE from "three";

const FALLBACK_MARK = "#2F6BEE";
const FALLBACK_INK = "#FFFFFF";
const HEX = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i;

const RINGS = [
  { radius: 1.5, tilt: 0.95, roll: 0.2, speed: 0.6, count: 6 },
  { radius: 1.95, tilt: -0.55, roll: 0.9, speed: -0.42, count: 9 },
  { radius: 2.4, tilt: 1.35, roll: -0.35, speed: 0.28, count: 12 },
];

function readColor(name: string, fallback: string): THREE.Color {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return new THREE.Color(HEX.test(value) ? value : fallback);
}

type Satellite = { mesh: THREE.Mesh; material: THREE.MeshBasicMaterial; ring: number; angle: number; index: number };

export function HomeLoader({ done, total }: { done: number; total: number }) {
  const stageRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const progressRef = useRef({ done, total });

  useEffect(() => {
    progressRef.current = { done, total };
  }, [done, total]);

  useEffect(() => {
    const stage = stageRef.current;
    const canvas = canvasRef.current;
    if (!stage || !canvas) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    renderer.setClearColor(0x000000, 0);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 50);
    camera.position.z = 7.2;

    const rig = new THREE.Group();
    scene.add(rig);

    // Core: a wireframe shell with a pulsing solid heart inside it.
    const shellGeometry = new THREE.WireframeGeometry(new THREE.IcosahedronGeometry(0.9, 1));
    const shellMaterial = new THREE.LineBasicMaterial({ transparent: true, opacity: 0.75 });
    rig.add(new THREE.LineSegments(shellGeometry, shellMaterial));
    const heartGeometry = new THREE.IcosahedronGeometry(0.42, 0);
    const heartMaterial = new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.3, depthWrite: false });
    rig.add(new THREE.Mesh(heartGeometry, heartMaterial));

    // Orbits: a thin tilted ring, with satellites riding it.
    const ringMaterials: THREE.MeshBasicMaterial[] = [];
    const satellites: Satellite[] = [];
    const satelliteGeometry = new THREE.SphereGeometry(0.075, 14, 10);
    RINGS.forEach((config, ringIndex) => {
      const group = new THREE.Group();
      group.rotation.set(config.tilt, 0, config.roll);
      rig.add(group);
      const ringMaterial = new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.2, depthWrite: false });
      ringMaterials.push(ringMaterial);
      group.add(new THREE.Mesh(new THREE.TorusGeometry(config.radius, 0.008, 4, 220), ringMaterial));
      for (let index = 0; index < config.count; index += 1) {
        const material = new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.22, depthWrite: false });
        const mesh = new THREE.Mesh(satelliteGeometry, material);
        group.add(mesh);
        satellites.push({ mesh, material, ring: ringIndex, angle: (index / config.count) * Math.PI * 2, index: satellites.length });
      }
    });
    const satelliteCount = satellites.length;

    const applyColors = () => {
      const mark = readColor("--mark", FALLBACK_MARK);
      const ink = readColor("--ink", FALLBACK_INK);
      shellMaterial.color.copy(mark);
      heartMaterial.color.copy(mark);
      ringMaterials.forEach((material) => material.color.copy(ink));
      satellites.forEach((satellite) => satellite.material.color.copy(mark));
    };
    applyColors();
    const themeObserver = new MutationObserver(applyColors);
    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    const colorScheme = window.matchMedia("(prefers-color-scheme: light)");
    colorScheme.addEventListener("change", applyColors);

    // Pointer: hover tilts the rig, a drag spins it.
    const pointer = { active: false, dragging: false, lastX: 0, nx: 0, ny: 0 };
    let dragOffset = 0;
    const target = { x: 0, y: 0 };
    const current = { x: 0, y: 0 };
    const updatePointer = (event: PointerEvent) => {
      const rect = stage.getBoundingClientRect();
      pointer.nx = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.ny = -(((event.clientY - rect.top) / rect.height) * 2 - 1);
    };
    const onPointerMove = (event: PointerEvent) => {
      updatePointer(event);
      pointer.active = true;
      if (pointer.dragging) {
        dragOffset += (event.clientX - pointer.lastX) * 0.01;
        pointer.lastX = event.clientX;
      }
    };
    const onPointerDown = (event: PointerEvent) => {
      pointer.dragging = true;
      pointer.lastX = event.clientX;
      stage.classList.add("is-dragging");
      stage.setPointerCapture(event.pointerId);
    };
    const onPointerUp = (event: PointerEvent) => {
      pointer.dragging = false;
      stage.classList.remove("is-dragging");
      if (stage.hasPointerCapture(event.pointerId)) stage.releasePointerCapture(event.pointerId);
    };
    const onPointerLeave = () => {
      if (!pointer.dragging) pointer.active = false;
    };
    stage.addEventListener("pointermove", onPointerMove);
    stage.addEventListener("pointerdown", onPointerDown);
    stage.addEventListener("pointerup", onPointerUp);
    stage.addEventListener("pointercancel", onPointerUp);
    stage.addEventListener("pointerleave", onPointerLeave);

    const resize = () => {
      const width = stage.clientWidth;
      const height = stage.clientHeight;
      if (width === 0 || height === 0) return;
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      // Narrow stages pull the camera back so the orbit still fits the width.
      camera.position.z = camera.aspect < 1 ? 9.6 : 7.2;
      camera.updateProjectionMatrix();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(stage);
    resize();

    let clock = 0;
    let spin = 0;
    let shown = 0;
    let last = performance.now();
    let frameId = 0;
    const draw = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      if (!reduced) {
        clock += dt;
        spin += dt * 0.22;
      }

      // Ease the displayed progress toward the real count so each step glides.
      const { done: doneNow, total: totalNow } = progressRef.current;
      const goal = totalNow > 0 ? Math.min(1, doneNow / totalNow) : 0;
      shown += (goal - shown) * Math.min(1, dt * 4);

      target.x = pointer.active ? pointer.ny * 0.4 : 0;
      target.y = pointer.active ? pointer.nx * 0.5 : 0;
      current.x += (target.x - current.x) * Math.min(1, dt * 6);
      current.y += (target.y - current.y) * Math.min(1, dt * 6);
      rig.rotation.set(current.x, spin + dragOffset + current.y, 0);

      heartMaterial.opacity = reduced ? 0.3 : 0.2 + 0.12 * Math.sin(clock * 2.2);
      satellites.forEach((satellite) => {
        const config = RINGS[satellite.ring];
        const angle = satellite.angle + clock * config.speed;
        satellite.mesh.position.set(Math.cos(angle) * config.radius, Math.sin(angle) * config.radius, 0);
        const lit = (satellite.index + 0.5) / satelliteCount < shown;
        satellite.material.opacity = lit ? 1 : 0.22;
      });

      renderer.render(scene, camera);
    };
    const loop = (now: number) => {
      draw(now);
      frameId = requestAnimationFrame(loop);
    };
    frameId = requestAnimationFrame(loop);

    return () => {
      cancelAnimationFrame(frameId);
      observer.disconnect();
      themeObserver.disconnect();
      colorScheme.removeEventListener("change", applyColors);
      stage.removeEventListener("pointermove", onPointerMove);
      stage.removeEventListener("pointerdown", onPointerDown);
      stage.removeEventListener("pointerup", onPointerUp);
      stage.removeEventListener("pointercancel", onPointerUp);
      stage.removeEventListener("pointerleave", onPointerLeave);
      scene.traverse((object) => {
        if (object instanceof THREE.Mesh || object instanceof THREE.LineSegments) {
          object.geometry.dispose();
          const materials = Array.isArray(object.material) ? object.material : [object.material];
          materials.forEach((material) => material.dispose());
        }
      });
      renderer.dispose();
    };
  }, []);

  return (
    <div className="q-loader" role="status" aria-live="polite">
      <div className="q-loader-stage" ref={stageRef}>
        <canvas ref={canvasRef} aria-hidden="true" />
      </div>
      <p className="q-loader-title">Loading your meetings</p>
      <p className="q-loader-count">{total > 0 ? `Checked ${done} of ${total}` : "Looking for meetings"}</p>
    </div>
  );
}
