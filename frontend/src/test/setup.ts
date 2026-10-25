import "@testing-library/jest-dom/vitest";
import { configure } from "@testing-library/react";

// V1-060 (DL-071 answer 13): the screen tests wait for the screen, not for a clock. A full run
// next to a PostgreSQL run (or on a busy CI runner) can starve a worker for seconds, and the
// library's default 1 second wait then fails a test whose screen is right. A wrong screen still
// fails: the wait only gives a slow worker time to finish rendering.
configure({ asyncUtilTimeout: 15_000 });
