import test from "node:test";
import assert from "node:assert/strict";
import { copyToClipboard } from "@/lib/clipboard";

test("copyToClipboard uses navigator.clipboard if available", async () => {
  let copiedText = "";
  const originalWindow = globalThis.window;
  const originalNavigator = globalThis.navigator;

  try {
    Object.defineProperty(globalThis, "window", {
      value: {},
      configurable: true,
      writable: true,
    });
    Object.defineProperty(globalThis, "navigator", {
      value: {
        clipboard: {
          writeText: async (text: string) => {
            copiedText = text;
          },
        },
      },
      configurable: true,
      writable: true,
    });

    const ok = await copyToClipboard("hello world");
    assert.equal(ok, true);
    assert.equal(copiedText, "hello world");
  } finally {
    Object.defineProperty(globalThis, "window", {
      value: originalWindow,
      configurable: true,
      writable: true,
    });
    Object.defineProperty(globalThis, "navigator", {
      value: originalNavigator,
      configurable: true,
      writable: true,
    });
  }
});

test("copyToClipboard falls back to document.execCommand when navigator.clipboard is unavailable", async () => {
  const originalWindow = globalThis.window;
  const originalNavigator = globalThis.navigator;
  const originalDocument = globalThis.document;
  let execCommandCalled = false;
  let execCommandAction = "";

  try {
    Object.defineProperty(globalThis, "window", {
      value: {},
      configurable: true,
      writable: true,
    });
    Object.defineProperty(globalThis, "navigator", {
      value: {},
      configurable: true,
      writable: true,
    });

    Object.defineProperty(globalThis, "document", {
      value: {
        createElement: (tag: string) => {
          return {
            tagName: tag.toUpperCase(),
            value: "",
            style: {},
            setAttribute: () => {},
            focus: () => {},
            select: () => {},
          };
        },
        body: {
          appendChild: () => {},
          removeChild: () => {},
        },
        execCommand: (command: string) => {
          execCommandCalled = true;
          execCommandAction = command;
          return true;
        },
      },
      configurable: true,
      writable: true,
    });

    const ok = await copyToClipboard("fallback text");
    assert.equal(ok, true);
    assert.equal(execCommandCalled, true);
    assert.equal(execCommandAction, "copy");
  } finally {
    Object.defineProperty(globalThis, "window", {
      value: originalWindow,
      configurable: true,
      writable: true,
    });
    Object.defineProperty(globalThis, "navigator", {
      value: originalNavigator,
      configurable: true,
      writable: true,
    });
    Object.defineProperty(globalThis, "document", {
      value: originalDocument,
      configurable: true,
      writable: true,
    });
  }
});
