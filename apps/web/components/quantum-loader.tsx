"use client";

/**
 * Quantum Singularity Awakening Loader
 *
 * Immersive 3D interactive WebGL simulation rendering a multi-layered
 * quantum core, concentric gyro rings with orbiting satellites, and
 * a 1,600+ particle constellation reacting to pointer gravity and shockwave pulses.
 */

import { useEffect, useRef, useState, useCallback } from "react";
import { createPortal } from "react-dom";
import * as THREE from "three";
import { Activity, Zap, ArrowRight } from "lucide-react";
import type { Phase } from "@/lib/mcp/client";

const STEPS = [
  {
    step: "01/04",
    label: "WAKING SERVERLESS COMPUTE",
    detail: "Instantiating ARM64 Lambda container in AWS ap-southeast-2…",
  },
  {
    step: "02/04",
    label: "INITIALIZING BEDROCK RUNTIME",
    detail: "Warming Claude Haiku 5-5 foundation model pipelines…",
  },
  {
    step: "03/04",
    label: "CONNECTING MCP AGENT PROTOCOL",
    detail: "Establishing SSE multiplexed transport & tool schema sync…",
  },
  {
    step: "04/04",
    label: "SYNTHESIS READY",
    detail: "Context graph hydrated. Serverless runtime active & operational.",
  },
];

const NEON_CYAN = "#38BDF8";
const NEON_BLUE = "#2F6BEE";
const NEON_WHITE = "#E0F2FE";

export function QuantumLoader({
  phase,
  enriching = false,
  progress = { done: 0, total: 0 },
  onBypass,
  hasCachedData = false,
}: {
  phase: Phase;
  enriching?: boolean;
  progress?: { done: number; total: number };
  onBypass?: () => void;
  hasCachedData?: boolean;
}) {
  const stageRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [pulseCount, setPulseCount] = useState(0);
  const [currentStepIndex, setCurrentStepIndex] = useState(0);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [minElapsed, setMinElapsed] = useState(false);
  const [isDismissing, setIsDismissing] = useState(false);
  const shockwaveTriggerRef = useRef<((power?: number) => void) | null>(null);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  // Guarantee user can experience the futuristic awakening sequence
  useEffect(() => {
    const t = setTimeout(() => setMinElapsed(true), 2800);
    return () => clearTimeout(t);
  }, []);

  const isReady = phase === "connected" && !enriching && minElapsed;

  // Handle completion: celebrate then dismiss
  useEffect(() => {
    if (isReady) {
      setCurrentStepIndex(3);
      if (shockwaveTriggerRef.current) shockwaveTriggerRef.current(2.5);
      const timer = setTimeout(() => {
        setIsDismissing(true);
        if (onBypass) {
          const dismissTimer = setTimeout(onBypass, 700);
          return () => clearTimeout(dismissTimer);
        }
      }, 2000);
      return () => clearTimeout(timer);
    }
  }, [isReady, onBypass]);

  // Centisecond stopwatch & stepped telemetry advancement
  useEffect(() => {
    const start = performance.now();
    const interval = setInterval(() => {
      const ms = Math.floor(performance.now() - start);
      setElapsedMs(ms);

      if (!isReady) {
        if (ms < 1000) {
          setCurrentStepIndex(0);
        } else if (ms < 2000) {
          setCurrentStepIndex(1);
        } else if (ms < 2800 || phase !== "connected") {
          setCurrentStepIndex(2);
        } else {
          setCurrentStepIndex(3);
        }
      }
    }, 40);

    return () => clearInterval(interval);
  }, [phase, isReady]);

  const triggerPulse = useCallback(() => {
    setPulseCount((c) => c + 1);
    if (shockwaveTriggerRef.current) {
      shockwaveTriggerRef.current(2.0);
    }
  }, []);

  // Three.js interactive quantum globe simulation
  useEffect(() => {
    const stage = stageRef.current;
    const canvas = canvasRef.current;
    if (!stage || !canvas) return;

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    // WebGL Renderer
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({
        canvas,
        antialias: true,
        alpha: true,
        powerPreference: "high-performance",
      });
    } catch {
      return;
    }

    renderer.setClearColor(0x000000, 0);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
    camera.position.z = 8.5;

    const rootGroup = new THREE.Group();
    // Position quantum globe in the upper-center sweet spot
    rootGroup.position.set(0, 0.5, 0);
    scene.add(rootGroup);

    // 1. Quantum Singularity Core: Luminous Wireframe Shell + Solid Heart
    const coreShellGeometry = new THREE.WireframeGeometry(new THREE.IcosahedronGeometry(0.95, 2));
    const coreShellMaterial = new THREE.LineBasicMaterial({
      color: new THREE.Color(NEON_CYAN),
      transparent: true,
      opacity: 0.9,
    });
    const coreShell = new THREE.LineSegments(coreShellGeometry, coreShellMaterial);
    rootGroup.add(coreShell);

    const innerHeartGeometry = new THREE.OctahedronGeometry(0.52, 1);
    const innerHeartMaterial = new THREE.MeshBasicMaterial({
      color: new THREE.Color(NEON_BLUE),
      transparent: true,
      opacity: 0.6,
      depthWrite: false,
    });
    const innerHeart = new THREE.Mesh(innerHeartGeometry, innerHeartMaterial);
    rootGroup.add(innerHeart);

    // 2. Three Concentric Gyro Rings with Orbiting Satellites
    const ringConfigs = [
      { radius: 1.75, tilt: 0.85, roll: 0.25, speed: 0.6, satCount: 6 },
      { radius: 2.35, tilt: -0.65, roll: 0.95, speed: -0.45, satCount: 8 },
      { radius: 3.0, tilt: 1.35, roll: -0.4, speed: 0.35, satCount: 12 },
    ];

    const ringGroups: THREE.Group[] = [];
    const ringMaterials: THREE.MeshBasicMaterial[] = [];
    const satellites: Array<{ mesh: THREE.Mesh; ringIndex: number; angle: number }> = [];
    const satGeometry = new THREE.SphereGeometry(0.075, 14, 12);

    ringConfigs.forEach((cfg, rIdx) => {
      const g = new THREE.Group();
      g.rotation.set(cfg.tilt, 0, cfg.roll);
      rootGroup.add(g);
      ringGroups.push(g);

      const rMat = new THREE.MeshBasicMaterial({
        color: new THREE.Color(NEON_CYAN),
        transparent: true,
        opacity: 0.35,
        depthWrite: false,
      });
      ringMaterials.push(rMat);
      g.add(new THREE.Mesh(new THREE.TorusGeometry(cfg.radius, 0.012, 6, 200), rMat));

      for (let s = 0; s < cfg.satCount; s++) {
        const sMat = new THREE.MeshBasicMaterial({
          color: new THREE.Color(NEON_WHITE),
          transparent: true,
          opacity: 0.95,
          depthWrite: false,
        });
        const satMesh = new THREE.Mesh(satGeometry, sMat);
        g.add(satMesh);
        satellites.push({
          mesh: satMesh,
          ringIndex: rIdx,
          angle: (s / cfg.satCount) * Math.PI * 2,
        });
      }
    });

    // 3. 1,600+ Particle Constellation Swirling in Orbital Vortex
    const PARTICLE_COUNT = 1600;
    const particleGeometry = new THREE.BufferGeometry();
    const positions = new Float32Array(PARTICLE_COUNT * 3);
    const originalPositions = new Float32Array(PARTICLE_COUNT * 3);
    const colors = new Float32Array(PARTICLE_COUNT * 3);

    const c1 = new THREE.Color(NEON_CYAN);
    const c2 = new THREE.Color(NEON_BLUE);
    const c3 = new THREE.Color(NEON_WHITE);

    for (let i = 0; i < PARTICLE_COUNT; i++) {
      const i3 = i * 3;
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(Math.random() * 2 - 1);
      const rad = 2.0 + Math.random() * 4.2;

      positions[i3] = rad * Math.sin(phi) * Math.cos(theta);
      positions[i3 + 1] = rad * Math.sin(phi) * Math.sin(theta);
      positions[i3 + 2] = rad * Math.cos(phi);

      originalPositions[i3] = positions[i3];
      originalPositions[i3 + 1] = positions[i3 + 1];
      originalPositions[i3 + 2] = positions[i3 + 2];

      const rChoice = Math.random();
      const col = rChoice < 0.5 ? c1 : rChoice < 0.85 ? c2 : c3;
      colors[i3] = col.r;
      colors[i3 + 1] = col.g;
      colors[i3 + 2] = col.b;
    }

    particleGeometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    particleGeometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));

    const particleMaterial = new THREE.PointsMaterial({
      vertexColors: true,
      size: 0.058,
      transparent: true,
      opacity: 0.8,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });

    const particleSystem = new THREE.Points(particleGeometry, particleMaterial);
    rootGroup.add(particleSystem);

    // Shockwave expansion state
    let shockwaveRadius = 0;
    let shockwavePower = 0;

    shockwaveTriggerRef.current = (power = 2.0) => {
      shockwaveRadius = 0.1;
      shockwavePower = power;
    };

    // Pointer Interactivity (Gravitational Attraction + 3D Drag Rotation)
    const pointer = {
      x: 0,
      y: 0,
      active: false,
      isDragging: false,
      lastX: 0,
      lastY: 0,
      dragRotX: 0,
      dragRotY: 0,
    };

    const handlePointerMove = (e: PointerEvent) => {
      const rect = stage.getBoundingClientRect();
      pointer.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -(((e.clientY - rect.top) / rect.height) * 2 - 1);
      pointer.active = true;

      if (pointer.isDragging) {
        const dx = e.clientX - pointer.lastX;
        const dy = e.clientY - pointer.lastY;
        pointer.dragRotY += dx * 0.008;
        pointer.dragRotX += dy * 0.008;
        pointer.lastX = e.clientX;
        pointer.lastY = e.clientY;
      }
    };

    const handlePointerDown = (e: PointerEvent) => {
      pointer.isDragging = true;
      pointer.lastX = e.clientX;
      pointer.lastY = e.clientY;
      try {
        stage.setPointerCapture(e.pointerId);
      } catch {
        // Safe fallback
      }
    };

    const handlePointerUp = (e: PointerEvent) => {
      pointer.isDragging = false;
      try {
        stage.releasePointerCapture(e.pointerId);
      } catch {
        // Safe fallback
      }
    };

    stage.addEventListener("pointermove", handlePointerMove);
    stage.addEventListener("pointerdown", handlePointerDown);
    stage.addEventListener("pointerup", handlePointerUp);
    stage.addEventListener("pointercancel", handlePointerUp);

    // Responsive Canvas Resizing
    const handleResize = () => {
      const w = stage.clientWidth;
      const h = stage.clientHeight;
      if (w === 0 || h === 0) return;
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.position.z = camera.aspect < 1 ? 10.5 : 8.5;
      rootGroup.position.set(0, camera.aspect < 1 ? 0.9 : 0.5, 0);
      camera.updateProjectionMatrix();
    };

    const resizeObserver = new ResizeObserver(handleResize);
    resizeObserver.observe(stage);
    handleResize();

    // Render loop
    let clock = 0;
    let lastTime = performance.now();
    let frameId = 0;
    let smoothRotX = 0;
    let smoothRotY = 0;

    const animate = (now: number) => {
      const dt = Math.min(0.06, (now - lastTime) / 1000);
      lastTime = now;

      if (!reduced) {
        clock += dt;
      }

      // Smooth camera tilt & rotation
      const targetRotX = pointer.dragRotX + (pointer.active ? pointer.y * 0.35 : 0);
      const targetRotY = clock * 0.28 + pointer.dragRotY + (pointer.active ? pointer.x * 0.45 : 0);
      smoothRotX += (targetRotX - smoothRotX) * Math.min(1, dt * 5);
      smoothRotY += (targetRotY - smoothRotY) * Math.min(1, dt * 5);
      rootGroup.rotation.set(smoothRotX, smoothRotY, 0);

      // Core pulsing
      const heartPulse = 1.0 + 0.18 * Math.sin(clock * 3.2);
      innerHeart.scale.set(heartPulse, heartPulse, heartPulse);
      coreShell.rotation.y = -clock * 0.3;
      coreShell.rotation.x = clock * 0.15;

      // Update Satellites
      satellites.forEach((sat) => {
        const cfg = ringConfigs[sat.ringIndex];
        const ang = sat.angle + clock * cfg.speed;
        sat.mesh.position.set(Math.cos(ang) * cfg.radius, Math.sin(ang) * cfg.radius, 0);
      });

      // Expand Shockwave
      if (shockwavePower > 0.01) {
        shockwaveRadius += dt * 8.5;
        shockwavePower *= Math.max(0, 1 - dt * 2.2);
      }

      // Default Quantum Vortex Swirl
      const posAttr = particleGeometry.attributes.position as THREE.BufferAttribute;
      const posArr = posAttr.array as Float32Array;
      const pointer3D = new THREE.Vector3(pointer.x * 3.5, pointer.y * 3.5, 0);

      for (let i = 0; i < PARTICLE_COUNT; i++) {
        const i3 = i * 3;
        let px = posArr[i3];
        let py = posArr[i3 + 1];
        let pz = posArr[i3 + 2];

        const ox = originalPositions[i3];
        const oy = originalPositions[i3 + 1];
        const oz = originalPositions[i3 + 2];

        // Orbital Nexus galaxy swirl
        const dist = Math.sqrt(px * px + py * py + pz * pz) || 1;
        const swirlSpeed = (1.6 / dist) * dt;
        const cosS = Math.cos(swirlSpeed);
        const sinS = Math.sin(swirlSpeed);
        const nx = px * cosS - pz * sinS;
        const nz = px * sinS + pz * cosS;
        px = nx;
        pz = nz;

        // Gravitational return force
        px += (ox - px) * dt * 0.45;
        py += (oy - py) * dt * 0.45;
        pz += (oz - pz) * dt * 0.45;

        // Pointer gravitational attraction
        if (pointer.active && !reduced) {
          const dx = pointer3D.x - px;
          const dy = pointer3D.y - py;
          const dz = pointer3D.z - pz;
          const pDist = Math.sqrt(dx * dx + dy * dy + dz * dz) + 0.1;
          if (pDist < 3.2) {
            const pull = (1.0 - pDist / 3.2) * 0.85 * dt;
            px += dx * pull;
            py += dy * pull;
            pz += dz * pull;
          }
        }

        // Pulse shockwave displacement
        if (shockwavePower > 0.05) {
          const dCore = Math.sqrt(px * px + py * py + pz * pz);
          const waveDiff = Math.abs(dCore - shockwaveRadius);
          if (waveDiff < 0.7) {
            const force = (1.0 - waveDiff / 0.7) * shockwavePower * 0.9;
            px += (px / dCore) * force;
            py += (py / dCore) * force;
            pz += (pz / dCore) * force;
          }
        }

        posArr[i3] = px;
        posArr[i3 + 1] = py;
        posArr[i3 + 2] = pz;
      }
      posAttr.needsUpdate = true;

      renderer.render(scene, camera);
      frameId = requestAnimationFrame(animate);
    };

    frameId = requestAnimationFrame(animate);

    return () => {
      cancelAnimationFrame(frameId);
      resizeObserver.disconnect();
      stage.removeEventListener("pointermove", handlePointerMove);
      stage.removeEventListener("pointerdown", handlePointerDown);
      stage.removeEventListener("pointerup", handlePointerUp);
      stage.removeEventListener("pointercancel", handlePointerUp);
      particleGeometry.dispose();
      particleMaterial.dispose();
      coreShellGeometry.dispose();
      coreShellMaterial.dispose();
      innerHeartGeometry.dispose();
      innerHeartMaterial.dispose();
      satGeometry.dispose();
      ringMaterials.forEach((m) => m.dispose());
      renderer.dispose();
    };
  }, [mounted]);

  const formatTimer = (ms: number) => {
    const totalSec = Math.floor(ms / 1000);
    const mm = String(Math.floor(totalSec / 60)).padStart(2, "0");
    const ss = String(totalSec % 60).padStart(2, "0");
    const cs = String(Math.floor((ms % 1000) / 10)).padStart(2, "0");
    return `${mm}:${ss}.${cs}`;
  };

  const currentStep = STEPS[currentStepIndex];
  const progressPercent = isReady
    ? 100
    : progress.total > 0
    ? Math.min(96, Math.floor(50 + (progress.done / progress.total) * 45))
    : phase === "connected"
    ? Math.min(92, Math.floor(65 + ((elapsedMs % 2000) / 2000) * 20))
    : Math.min(60, Math.floor(15 + currentStepIndex * 15 + ((elapsedMs % 1000) / 1000) * 10));

  const stepHeading = isReady
    ? "ALL SYSTEMS OPERATIONAL"
    : currentStepIndex === 3 && progress.total > 0
    ? `SYNCHRONIZING INTELLIGENCE (${progress.done}/${progress.total})`
    : currentStep.label;

  const stepDetail = isReady
    ? "MCP stream established. Intelligence graph synchronized and compute online."
    : currentStepIndex === 3 && progress.total > 0
    ? `Synchronizing meeting memory graph and audio pipelines (${progress.done} of ${progress.total})…`
    : currentStep.detail;

  if (!mounted) return null;

  return createPortal(
    <div
      className={`q-quantum-overlay ${isDismissing ? "is-dismissing" : ""}`}
      role="dialog"
      aria-modal="true"
      aria-label="Quotient Awakening Telemetry"
    >
      {/* 3D WebGL Quantum Simulation Canvas & Ambient Gyro Glow */}
      <div className="q-quantum-canvas-wrap" ref={stageRef}>
        {/* CSS/SVG Ambient Orbit Rings (Always visible behind WebGL) */}
        <div className="q-quantum-ambient-rings" aria-hidden="true">
          <div className="q-quantum-ambient-ring ring-1" />
          <div className="q-quantum-ambient-ring ring-2" />
          <div className="q-quantum-ambient-ring ring-3" />
          <div className="q-quantum-ambient-core" />
        </div>
        <canvas ref={canvasRef} aria-hidden="true" />
      </div>

      {/* Cybernetic HUD Interface */}
      <div className="q-quantum-hud">
        {/* Top Telemetry Header */}
        <header className="q-quantum-head">
          <div className="q-quantum-brand">
            <span className="q-quantum-pulse-beacon" aria-hidden="true">
              <span className="q-quantum-pulse-beacon-inner" />
            </span>
            <div className="q-quantum-brand-text">
              <span className="q-quantum-sys-title">QUOTIENT AWAKENING</span>
              <span className="q-quantum-sub-title">ON-DEMAND SERVERLESS RUNTIME</span>
            </div>
          </div>

          <div className="q-quantum-timer-badge">
            <Activity size={14} className="q-quantum-spin-icon" aria-hidden="true" />
            <span>T+ {formatTimer(elapsedMs)}</span>
          </div>
        </header>

        {/* Center Hero Space - Open for 3D Quantum Globe */}
        <div className="q-quantum-hero-space" aria-hidden="true">
          <div className="q-quantum-interact-hint">
            <span>DRAG TO ROTATE SINGULARITY • HOVER TO ATTRACT STARS</span>
          </div>
        </div>

        {/* Bottom Floating Glass Status Console */}
        <div className="q-quantum-bottom-deck">
          <div className="q-quantum-stage-card">
            <div className="q-quantum-step-meta">
              <span className="q-quantum-step-pill">STEP {currentStep.step}</span>
              <span className="q-quantum-step-status">
                {isReady ? "ONLINE" : phase === "connected" ? "SYNCHRONIZING" : "WARMING UP COMPUTE"}
              </span>
            </div>

            <h2 className="q-quantum-step-heading">{stepHeading}</h2>
            <p className="q-quantum-step-detail">{stepDetail}</p>

            {/* Stepper Progress Bar */}
            <div
              className="q-quantum-progress-bar-bg"
              role="progressbar"
              aria-valuenow={progressPercent}
              aria-valuemin={0}
              aria-valuemax={100}
            >
              <div
                className={`q-quantum-progress-bar-fill ${isReady ? "is-connected" : ""}`}
                style={{ width: `${progressPercent}%` }}
              />
            </div>

            {/* Interactive Pulse & Bypass Buttons */}
            <div className="q-quantum-actions">
              <button
                type="button"
                className="q-quantum-pulse-btn"
                onClick={triggerPulse}
                aria-label="Pulse Quantum Shockwave"
              >
                <Zap size={14} aria-hidden="true" />
                <span>Pulse Energy {pulseCount > 0 ? `(${pulseCount})` : ""}</span>
              </button>

              {hasCachedData && onBypass ? (
                <button
                  type="button"
                  className="q-quantum-bypass-btn"
                  onClick={onBypass}
                >
                  <span>Explore Cached Meetings</span>
                  <ArrowRight size={14} aria-hidden="true" />
                </button>
              ) : null}
            </div>
          </div>
        </div>
      </div>
    </div>,
    document.body
  );
}
