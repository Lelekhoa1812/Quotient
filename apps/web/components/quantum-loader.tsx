"use client";

/**
 * Motivation vs Logic
 * Motivation: When Quotient's serverless compute is sleeping (scale-to-zero), a user opening
 * the portal or waiting for cold start needs a mesmerizing, interactive, futuristic experience
 * that reassures them with live telemetry, multi-step progress, and tactile agency while the
 * AWS Lambda container and Bedrock Haiku runtime wake up.
 * Logic: WebGL Three.js canvas featuring a quantum singularity core, 3 concentric orbital gyro
 * rings, and 1,400+ interactive particles with 3 switchable visual modes (Orbital Nexus, Neural
 * Matrix, Hyper-Warp), cursor gravitational physics, click/tap shockwave bursts, live centisecond
 * telemetry timer, 4-stage waking progression, and an instant offline bypass option.
 */

import { useEffect, useRef, useState, useCallback } from "react";
import { createPortal } from "react-dom";
import * as THREE from "three";
import { Activity, Cpu, Radio, Sparkles, Zap, ArrowRight, Layers } from "lucide-react";
import type { Phase } from "@/lib/mcp/client";

export type VisualMode = "nexus" | "neural" | "warp";

interface StepInfo {
  step: string;
  label: string;
  detail: string;
}

const STEPS: StepInfo[] = [
  {
    step: "01/04",
    label: "WAKING SERVERLESS COMPUTE",
    detail: "Instantiating ARM64 Lambda container in AWS ap-southeast-2…",
  },
  {
    step: "02/04",
    label: "INITIALIZING BEDROCK RUNTIME",
    detail: "Loading Anthropic Claude Haiku 5-5 & Converse prompt caches…",
  },
  {
    step: "03/04",
    label: "MCP PROTOCOL HANDSHAKE",
    detail: "Negotiating Streamable HTTP transport v2025-11-25…",
  },
  {
    step: "04/04",
    label: "SYNCHRONIZING INTELLIGENCE GRAPH",
    detail: "Attaching meeting memory store & audio pipelines…",
  },
];

const FALLBACK_MARK = "#2F6BEE";
const FALLBACK_INK = "#FFFFFF";
const HEX = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i;

function readColor(name: string, fallback: string): THREE.Color {
  if (typeof window === "undefined") return new THREE.Color(fallback);
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return new THREE.Color(HEX.test(value) ? value : fallback);
}

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
  const [mode, setMode] = useState<VisualMode>("nexus");
  const [pulseCount, setPulseCount] = useState(0);
  const [currentStepIndex, setCurrentStepIndex] = useState(0);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [minElapsed, setMinElapsed] = useState(false);
  const [isDismissing, setIsDismissing] = useState(false);
  const shockwaveTriggerRef = useRef<((power?: number) => void) | null>(null);
  const modeRef = useRef<VisualMode>(mode);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  // Guarantee user can see and interact with the futuristic awakening sequence
  useEffect(() => {
    const t = setTimeout(() => setMinElapsed(true), 2800);
    return () => clearTimeout(t);
  }, []);

  const isReady = phase === "connected" && !enriching && minElapsed;

  useEffect(() => {
    modeRef.current = mode;
  }, [mode]);

  // Handle completion: when connection and enrichment complete, celebrate then dismiss
  useEffect(() => {
    if (isReady) {
      setCurrentStepIndex(3);
      if (shockwaveTriggerRef.current) shockwaveTriggerRef.current(2.5);
      const timer = setTimeout(() => {
        setIsDismissing(true);
        if (onBypass) {
          const dismissTimer = setTimeout(onBypass, 600);
          return () => clearTimeout(dismissTimer);
        }
      }, 700);
      return () => clearTimeout(timer);
    }
  }, [isReady, onBypass]);

  // Centisecond stopwatch & stepped telemetry advancement
  useEffect(() => {
    const start = performance.now();
    const interval = setInterval(() => {
      const ms = Math.floor(performance.now() - start);
      setElapsedMs(ms);

      // Advance through steps realistically based on cold start timing & connection
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
      shockwaveTriggerRef.current(1.8);
    }
  }, []);

  // Three.js interactive canvas simulation
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
    scene.add(rootGroup);

    // 1. Quantum Singularity Core
    const coreShellGeometry = new THREE.WireframeGeometry(new THREE.IcosahedronGeometry(0.85, 2));
    const coreShellMaterial = new THREE.LineBasicMaterial({
      color: new THREE.Color(FALLBACK_MARK),
      transparent: true,
      opacity: 0.8,
    });
    const coreShell = new THREE.LineSegments(coreShellGeometry, coreShellMaterial);
    rootGroup.add(coreShell);

    const innerHeartGeometry = new THREE.OctahedronGeometry(0.48, 1);
    const innerHeartMaterial = new THREE.MeshBasicMaterial({
      color: new THREE.Color(FALLBACK_MARK),
      transparent: true,
      opacity: 0.45,
      depthWrite: false,
    });
    const innerHeart = new THREE.Mesh(innerHeartGeometry, innerHeartMaterial);
    rootGroup.add(innerHeart);

    // 2. Three Concentric Gyro Rings
    const ringConfigs = [
      { radius: 1.6, tilt: 0.85, roll: 0.25, speed: 0.55, satCount: 6 },
      { radius: 2.2, tilt: -0.65, roll: 0.95, speed: -0.42, satCount: 8 },
      { radius: 2.85, tilt: 1.35, roll: -0.4, speed: 0.32, satCount: 12 },
    ];

    const ringGroups: THREE.Group[] = [];
    const ringMaterials: THREE.MeshBasicMaterial[] = [];
    const satellites: Array<{ mesh: THREE.Mesh; ringIndex: number; angle: number }> = [];
    const satGeometry = new THREE.SphereGeometry(0.065, 12, 10);

    ringConfigs.forEach((cfg, rIdx) => {
      const g = new THREE.Group();
      g.rotation.set(cfg.tilt, 0, cfg.roll);
      rootGroup.add(g);
      ringGroups.push(g);

      const rMat = new THREE.MeshBasicMaterial({
        color: new THREE.Color(FALLBACK_INK),
        transparent: true,
        opacity: 0.24,
        depthWrite: false,
      });
      ringMaterials.push(rMat);
      g.add(new THREE.Mesh(new THREE.TorusGeometry(cfg.radius, 0.009, 4, 180), rMat));

      for (let s = 0; s < cfg.satCount; s++) {
        const sMat = new THREE.MeshBasicMaterial({
          color: new THREE.Color(FALLBACK_MARK),
          transparent: true,
          opacity: 0.85,
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

    // 3. 1,400+ Particle Constellation
    const PARTICLE_COUNT = 1400;
    const particleGeometry = new THREE.BufferGeometry();
    const positions = new Float32Array(PARTICLE_COUNT * 3);
    const originalPositions = new Float32Array(PARTICLE_COUNT * 3);
    const velocities = new Float32Array(PARTICLE_COUNT * 3);

    for (let i = 0; i < PARTICLE_COUNT; i++) {
      const i3 = i * 3;
      // Spherical shell distribution with variance
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(Math.random() * 2 - 1);
      const rad = 2.2 + Math.random() * 3.8;

      positions[i3] = rad * Math.sin(phi) * Math.cos(theta);
      positions[i3 + 1] = rad * Math.sin(phi) * Math.sin(theta);
      positions[i3 + 2] = rad * Math.cos(phi);

      originalPositions[i3] = positions[i3];
      originalPositions[i3 + 1] = positions[i3 + 1];
      originalPositions[i3 + 2] = positions[i3 + 2];

      velocities[i3] = (Math.random() - 0.5) * 0.02;
      velocities[i3 + 1] = (Math.random() - 0.5) * 0.02;
      velocities[i3 + 2] = (Math.random() - 0.5) * 0.02;
    }

    particleGeometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));

    const particleMaterial = new THREE.PointsMaterial({
      color: new THREE.Color(FALLBACK_MARK),
      size: 0.048,
      transparent: true,
      opacity: 0.65,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });

    const particleSystem = new THREE.Points(particleGeometry, particleMaterial);
    rootGroup.add(particleSystem);

    // Shockwave expansion state
    let shockwaveRadius = 0;
    let shockwavePower = 0;

    shockwaveTriggerRef.current = (power = 1.8) => {
      shockwaveRadius = 0.1;
      shockwavePower = power;
    };

    // Color synchronization
    const updateColors = () => {
      const mark = readColor("--mark", FALLBACK_MARK);
      const ink = readColor("--ink", FALLBACK_INK);
      coreShellMaterial.color.copy(mark);
      innerHeartMaterial.color.copy(mark);
      particleMaterial.color.copy(mark);
      ringMaterials.forEach((m) => m.color.copy(ink));
    };
    updateColors();

    const observer = new MutationObserver(updateColors);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

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
      stage.setPointerCapture(e.pointerId);
      // Trigger instant quantum ripple on click/tap
      shockwaveRadius = 0.1;
      shockwavePower = 1.6;
    };

    const handlePointerUp = (e: PointerEvent) => {
      pointer.isDragging = false;
      if (stage.hasPointerCapture(e.pointerId)) {
        stage.releasePointerCapture(e.pointerId);
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
      camera.position.z = camera.aspect < 1 ? 11.0 : 8.5;
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
      const targetRotY = clock * 0.25 + pointer.dragRotY + (pointer.active ? pointer.x * 0.45 : 0);
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
        shockwaveRadius += dt * 7.5;
        shockwavePower *= Math.max(0, 1 - dt * 2.2);
      }

      // Dynamic Particle Simulation based on VisualMode
      const activeMode = modeRef.current;
      const posAttr = particleGeometry.attributes.position as THREE.BufferAttribute;
      const posArr = posAttr.array as Float32Array;

      // Unproject pointer for 3D cursor attraction
      const pointer3D = new THREE.Vector3(pointer.x * 3.5, pointer.y * 3.5, 0);

      for (let i = 0; i < PARTICLE_COUNT; i++) {
        const i3 = i * 3;
        let px = posArr[i3];
        let py = posArr[i3 + 1];
        let pz = posArr[i3 + 2];

        const ox = originalPositions[i3];
        const oy = originalPositions[i3 + 1];
        const oz = originalPositions[i3 + 2];

        if (activeMode === "warp") {
          // Relativistic warp streak moving along Z towards camera
          pz += dt * 8.0;
          if (pz > 5.0) pz = -6.0;
          px = ox * (1 + (pz + 6.0) * 0.12);
          py = oy * (1 + (pz + 6.0) * 0.12);
        } else if (activeMode === "neural") {
          // Harmonic wave matrix
          const wave = Math.sin(clock * 2.0 + ox * 0.8 + oy * 0.8) * 0.6;
          pz = oz + wave;
          px = ox + Math.cos(clock + oz) * 0.15;
          py = oy + Math.sin(clock + oz) * 0.15;
        } else {
          // Orbital Nexus swirl
          const dist = Math.sqrt(px * px + py * py + pz * pz) || 1;
          const swirlSpeed = (1.5 / dist) * dt;
          const cosS = Math.cos(swirlSpeed);
          const sinS = Math.sin(swirlSpeed);
          const nx = px * cosS - pz * sinS;
          const nz = px * sinS + pz * cosS;
          px = nx;
          pz = nz;
          // Return force to orbital envelope
          px += (ox - px) * dt * 0.4;
          py += (oy - py) * dt * 0.4;
          pz += (oz - pz) * dt * 0.4;
        }

        // Pointer gravitational pull if active
        if (pointer.active && !reduced) {
          const dx = pointer3D.x - px;
          const dy = pointer3D.y - py;
          const dz = pointer3D.z - pz;
          const pDist = Math.sqrt(dx * dx + dy * dy + dz * dz) + 0.1;
          if (pDist < 3.2) {
            const pull = (1.0 - pDist / 3.2) * 0.8 * dt;
            px += dx * pull;
            py += dy * pull;
            pz += dz * pull;
          }
        }

        // Shockwave displacement blast
        if (shockwavePower > 0.05) {
          const dCore = Math.sqrt(px * px + py * py + pz * pz);
          const waveDiff = Math.abs(dCore - shockwaveRadius);
          if (waveDiff < 0.6) {
            const force = (1.0 - waveDiff / 0.6) * shockwavePower * 0.8;
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
      observer.disconnect();
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
  }, []);

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
      {/* 3D WebGL Quantum Simulation Canvas */}
      <div className="q-quantum-canvas-wrap" ref={stageRef}>
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

        {/* Central Waking Telemetry Card */}
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
          <div className="q-quantum-progress-bar-bg" role="progressbar" aria-valuenow={progressPercent} aria-valuemin={0} aria-valuemax={100}>
            <div
              className={`q-quantum-progress-bar-fill ${isReady ? "is-connected" : ""}`}
              style={{ width: `${progressPercent}%` }}
            />
          </div>

          {/* 4 Multi-step indicators */}
          <div className="q-quantum-stepper-grid">
            {STEPS.map((step, idx) => {
              const isPast = idx < currentStepIndex || isReady;
              const isCurrent = idx === currentStepIndex && !isReady;
              return (
                <div
                  key={step.step}
                  className={`q-quantum-stepper-node ${isPast ? "is-complete" : ""} ${isCurrent ? "is-active" : ""}`}
                >
                  <span className="q-quantum-stepper-line" />
                  <span className="q-quantum-stepper-label">{step.step}</span>
                </div>
              );
            })}
          </div>
        </div>

        {/* Interactive Controls Deck */}
        <div className="q-quantum-deck">
          <div className="q-quantum-modes" role="group" aria-label="Visual mode">
            <span className="q-quantum-modes-label">
              <Layers size={13} aria-hidden="true" />
              <span>SIMULATION MODE:</span>
            </span>
            {(["nexus", "neural", "warp"] as const).map((m) => (
              <button
                key={m}
                type="button"
                className={`q-quantum-mode-btn ${mode === m ? "is-active" : ""}`}
                onClick={() => setMode(m)}
              >
                {m === "nexus" ? "Orbital Nexus" : m === "neural" ? "Neural Matrix" : "Hyper-Warp"}
              </button>
            ))}
          </div>

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

        {/* Bottom Hardware Telemetry Bar */}
        <footer className="q-quantum-telemetry-bar">
          <div className="q-quantum-tele-node">
            <Radio size={12} aria-hidden="true" />
            <span>REGION:</span>
            <strong>ap-southeast-2</strong>
          </div>
          <div className="q-quantum-tele-node">
            <Cpu size={12} aria-hidden="true" />
            <span>ENGINE:</span>
            <strong>Bedrock Haiku 5-5</strong>
          </div>
          <div className="q-quantum-tele-node">
            <Sparkles size={12} aria-hidden="true" />
            <span>PROMPT CACHING:</span>
            <strong>Active (Converse)</strong>
          </div>
          <div className="q-quantum-tele-node is-status">
            <span className={`q-quantum-status-dot ${phase === "connected" ? "is-online" : ""}`} />
            <span>{phase === "connected" ? "COMPUTE READY" : "SCALE-TO-ZERO SERVERLESS"}</span>
          </div>
        </footer>
      </div>
    </div>,
    document.body
  );
}
