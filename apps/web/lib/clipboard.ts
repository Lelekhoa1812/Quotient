/**
 * Motivation vs Logic
 * Motivation: In non-secure contexts (HTTP over public IP/DNS), navigator.clipboard
 * is undefined and throws. Users need reliable clipboard copying across all browsers
 * and network origins, with fallback to document.execCommand('copy').
 * Logic: Try navigator.clipboard.writeText if available; fallback to an offscreen
 * textarea element with document.execCommand('copy'). Returns true if succeeded.
 */

export async function copyToClipboard(text: string): Promise<boolean> {
  if (typeof window === "undefined") return false;

  if (navigator?.clipboard && typeof navigator.clipboard.writeText === "function") {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // Fall through to fallback
    }
  }

  try {
    const textArea = document.createElement("textarea");
    textArea.value = text;
    // Prevent scrolling or displaying
    textArea.style.position = "fixed";
    textArea.style.top = "-9999px";
    textArea.style.left = "-9999px";
    textArea.style.opacity = "0";
    textArea.style.pointerEvents = "none";
    textArea.setAttribute("readonly", "");
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    const successful = document.execCommand("copy");
    document.body.removeChild(textArea);
    return successful;
  } catch {
    return false;
  }
}
