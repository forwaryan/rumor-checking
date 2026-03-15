var version = process.versions && process.versions.node ? process.versions.node : "";
var parts = version.split(".").map(function (part) {
  return parseInt(part, 10) || 0;
});

function compare(left, right) {
  for (var i = 0; i < Math.max(left.length, right.length); i += 1) {
    var leftValue = left[i] || 0;
    var rightValue = right[i] || 0;
    if (leftValue > rightValue) {
      return 1;
    }
    if (leftValue < rightValue) {
      return -1;
    }
  }
  return 0;
}

var minimum = [18, 18, 0];
var recommended = [20, 9, 0];

if (!version || compare(parts, minimum) < 0) {
  console.error(
    [
      "Node.js version too old for this frontend.",
      "Detected: " + (version || "unknown"),
      "Required: >= 18.18.0",
      "Recommended: >= 20.9.0",
      "If you are on Windows with a WSL workspace, use frontend/run-local-windows-checks.ps1",
      "or frontend/start-local-windows.ps1 from a Windows shell.",
    ].join("\n")
  );
  process.exit(1);
}

if (compare(parts, recommended) < 0) {
  console.warn(
    [
      "Node.js version meets the minimum requirement but is below the recommended baseline.",
      "Detected: " + version,
      "Recommended: >= 20.9.0",
    ].join("\n")
  );
}
