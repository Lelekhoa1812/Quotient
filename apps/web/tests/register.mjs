// Registers the "@/" path alias from tsconfig so node's built-in test runner can load app modules.
import { register } from "node:module";

register("./alias.mjs", import.meta.url);
