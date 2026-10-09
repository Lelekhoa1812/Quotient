import assert from "node:assert/strict";
import test from "node:test";
import { isDrawable } from "@/lib/diagram";

test("only a flowchart or a sequence diagram is handed to the renderer", () => {
  for (const fine of ["flowchart TD\n A --> B", "graph LR\n A --> B", "  sequenceDiagram\n A->>B: hi", "flowchart\tTD"]) assert.equal(isDrawable(fine), true, fine);
  for (const refused of ["", "   ", "gantt\n x", "xychart-beta\n bar [1]", "radar-beta\n axis a", "architecture-beta\n group g(cloud)[G]", "classDiagram\n A <|-- B",
    "stateDiagram-v2\n [*] --> A", "%% flowchart\ngantt", "flowchartTD", "Flowchart TD"]) assert.equal(isDrawable(refused), false, refused);
});
