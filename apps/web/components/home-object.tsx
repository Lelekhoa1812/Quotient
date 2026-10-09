"use client";

import { useEffect, useRef } from "react";
import * as THREE from "three";

/**
 * Motivation vs Logic
 * Motivation: The home background is a full-screen field of sparks, with no
 * torus. Light mode uses black sparks, dark mode uses white.
 * Logic: Seed positions, phase, speed, and size once per mount. Each spark
 * rises in opacity, falls, stays gone, then repeats. Reduced motion holds
 * every spark at a steady mid opacity.
 */

/**
 * Bugs vs Fixes
 * Bug: The torus mesh was still drawn, so the corner donut stayed on screen.
 * Fix: The scene is only the seeded point field. Theme swaps the point color.
 */
function isLightTheme(): boolean {
  const theme = document.documentElement.dataset.theme;
  if (theme === "light") return true;
  if (theme === "dark") return false;
  return window.matchMedia("(prefers-color-scheme: light)").matches;
}

function mulberry32(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const STAR_COUNT = 108;

function buildStars(): { points: THREE.Points; geometry: THREE.BufferGeometry; material: THREE.ShaderMaterial } {
  const random = mulberry32((Math.random() * 0xffffffff) >>> 0);
  const positions = new Float32Array(STAR_COUNT * 3);
  const phases = new Float32Array(STAR_COUNT);
  const speeds = new Float32Array(STAR_COUNT);
  const sizes = new Float32Array(STAR_COUNT);
  for (let i = 0; i < STAR_COUNT; i += 1) {
    positions[i * 3] = random() * 2 - 1;
    positions[i * 3 + 1] = random() * 2 - 1;
    positions[i * 3 + 2] = 0;
    phases[i] = random();
    speeds[i] = 0.18 + random() * 0.14;
    sizes[i] = 2.8 + random() * 2.4;
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute("aPhase", new THREE.BufferAttribute(phases, 1));
  geometry.setAttribute("aSpeed", new THREE.BufferAttribute(speeds, 1));
  geometry.setAttribute("aSize", new THREE.BufferAttribute(sizes, 1));
  const material = new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    toneMapped: false,
    uniforms: {
      uTime: { value: 0 },
      uMotion: { value: 1 },
      uPixel: { value: 1 },
      uColor: { value: new THREE.Color("#FFFFFF") },
    },
    vertexShader: `
      attribute float aPhase;
      attribute float aSpeed;
      attribute float aSize;
      uniform float uTime;
      uniform float uMotion;
      uniform float uPixel;
      varying float vAlpha;
      void main() {
        float t = fract(uTime * aSpeed + aPhase);
        float rise = smoothstep(0.0, 0.28, t);
        float fall = 1.0 - smoothstep(0.48, 0.78, t);
        float life = step(t, 0.78);
        float wave = min(rise, fall) * life;
        vAlpha = mix(0.42, wave, uMotion);
        float scale = mix(1.0, mix(0.7, 1.0, wave), uMotion);
        gl_PointSize = aSize * uPixel * scale;
        gl_Position = vec4(position.xy, 0.0, 1.0);
      }
    `,
    fragmentShader: `
      uniform vec3 uColor;
      varying float vAlpha;
      void main() {
        float d = length(gl_PointCoord - vec2(0.5));
        if (d > 0.5) discard;
        float edge = smoothstep(0.5, 0.15, d);
        float a = vAlpha * edge;
        gl_FragColor = vec4(uColor * a, a);
      }
    `,
  });
  return { points: new THREE.Points(geometry, material), geometry, material };
}

export function HomeObject() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const frameRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const frame = frameRef.current;
    if (!canvas || !frame) return;
    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    renderer.setClearColor(0x000000, 0);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.NoToneMapping;
    const scene = new THREE.Scene();
    const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
    const stars = buildStars();
    scene.add(stars.points);
    const applyColor = () => {
      stars.material.uniforms.uColor.value.set(isLightTheme() ? "#000000" : "#FFFFFF");
    };
    applyColor();
    const themeObserver = new MutationObserver(applyColor);
    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    const colorScheme = window.matchMedia("(prefers-color-scheme: light)");
    colorScheme.addEventListener("change", applyColor);
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) stars.material.uniforms.uMotion.value = 0;
    let frameId = 0;
    let last = performance.now();
    const draw = (now: number) => {
      const delta = Math.min(0.05, (now - last) / 1000);
      last = now;
      if (!reduced) stars.material.uniforms.uTime.value += delta;
      renderer.render(scene, camera);
    };
    const resize = () => {
      const width = frame.clientWidth;
      const height = frame.clientHeight;
      if (width === 0 || height === 0) return;
      const pixelRatio = Math.min(window.devicePixelRatio, 2);
      renderer.setPixelRatio(pixelRatio);
      stars.material.uniforms.uPixel.value = pixelRatio;
      renderer.setSize(width, height, false);
      draw(performance.now());
    };
    const observer = new ResizeObserver(resize);
    observer.observe(frame);
    window.addEventListener("resize", resize);
    resize();
    const loop = (now: number) => {
      draw(now);
      frameId = requestAnimationFrame(loop);
    };
    if (!reduced) frameId = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(frameId);
      window.removeEventListener("resize", resize);
      colorScheme.removeEventListener("change", applyColor);
      themeObserver.disconnect();
      observer.disconnect();
      stars.geometry.dispose();
      stars.material.dispose();
      renderer.dispose();
    };
  }, []);

  return (
    <div className="q-spark-field" ref={frameRef} aria-hidden="true">
      <canvas ref={canvasRef} />
    </div>
  );
}
