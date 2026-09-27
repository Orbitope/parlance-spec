/**
 * The conformance vectors, run against this package's own source — the same
 * runner core uses, so the MIT runtime is checked directly, not only through
 * the editor's re-exports.
 */
import * as runtime from "../src/index.js";
import { runConformanceSuite } from "./conformanceRunner.js";

runConformanceSuite(runtime);
