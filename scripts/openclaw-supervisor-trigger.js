const result = await tools.call("exec", {
  command:
    "/Users/sokompheak/Development/property-rental-management/scripts/openclaw-supervisor-preflight.sh",
});

const output = String(result?.result?.details?.aggregated ?? "").trim();
if (!output) {
  throw new Error("Property Rental supervisor preflight returned no output");
}

let current;
try {
  current = JSON.parse(output);
} catch {
  throw new Error("Property Rental supervisor preflight returned invalid JSON");
}

const fingerprint = JSON.stringify({
  head: current.head,
  status: current.status,
  next_action: current.next_action,
  blockers: current.blockers,
  worktree: current.worktree,
});
const fire = current.actionable === true && trigger.state?.fingerprint !== fingerprint;

json({
  fire,
  message: fire ? `Preflight approved actionable state: ${output}` : undefined,
  state: {
    fingerprint,
    actionable: current.actionable === true,
    status: current.status,
  },
});
