#!/bin/bash
# SELENE preflight environment check.
#
# Fast, read-only. Run this before a demo to find out what is missing BEFORE the
# audience is watching. It starts nothing and installs nothing.
#
# Usage:
#   bash scripts/check_env.sh
#
# Env overrides:
#   SELENE_DEST       built workspace to check (default $HOME/selene)
#   SELENE_ROS_SETUP  ROS 2 setup.bash (default /opt/ros/jazzy/setup.bash)
#
# Exit code: 0 if every hard check passed, 1 otherwise.
#
# HONEST SCOPE — what this script does NOT check:
#   * that Gazebo can actually create a rendering/physics session (needs a real
#     `gz sim` run, and on WSL2 depends on the GPU/GL setup)
#   * that the ROS 2 graph forms, that DDS discovery works, or that any node runs
#   * that the dashboard connects to rosbridge or that robots move
#   * whether lunar gravity is honoured by Gazebo (world SDF only checked as XML)
# Those require actually launching the stack; see scripts/validate_phase5.sh.

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${SELENE_DEST:-$HOME/selene}"
ROS_SETUP="${SELENE_ROS_SETUP:-/opt/ros/jazzy/setup.bash}"

PASS=0
FAIL=0
WARN=0
FAILED_ITEMS=()
WARNED_ITEMS=()

ok()   { echo "  [ OK ]   $1"; PASS=$((PASS + 1)); }
bad()  { echo "  [FAIL]   $1"; echo "           -> $2"; FAIL=$((FAIL + 1)); FAILED_ITEMS+=("$1"); }
warn() { echo "  [WARN]   $1"; echo "           -> $2"; WARN=$((WARN + 1)); WARNED_ITEMS+=("$1"); }
note() { echo "  [ ?  ]   $1"; }

echo "============================================"
echo " SELENE preflight environment check"
echo " repo:      $SRC"
echo " workspace: $DEST"
echo "============================================"
echo ""

# --------------------------------------------------------------------------
echo "-- Toolchain --"

if command -v ros2 > /dev/null 2>&1; then
    ok "ros2 on PATH ($(command -v ros2))"
elif [ -f "$ROS_SETUP" ]; then
    warn "ros2 not on PATH, but $ROS_SETUP exists" \
         "run: source $ROS_SETUP   (then re-run this check)"
else
    bad "ros2 not found and no $ROS_SETUP" \
        "install ROS 2: bash $SRC/scripts/setup_wsl2.sh"
fi

if command -v gz > /dev/null 2>&1; then
    GZ_VER="$(gz sim --versions 2>/dev/null | head -1)"
    ok "gz on PATH ($(command -v gz))${GZ_VER:+, sim version: $GZ_VER}"
else
    bad "gz (Gazebo) not found on PATH" \
        "install Gazebo Harmonic: bash $SRC/scripts/setup_wsl2.sh"
fi

if command -v node > /dev/null 2>&1; then
    NODE_V="$(node -v)"
    NODE_MAJOR="$(echo "$NODE_V" | sed -n 's/^v\([0-9][0-9]*\).*/\1/p')"
    NODE_MAJOR="${NODE_MAJOR:-0}"
    if [ "$NODE_MAJOR" -ge 18 ]; then
        ok "node $NODE_V ($(command -v node))"
    else
        bad "node $NODE_V is older than the required v18" \
            "install Node.js 18+: bash $SRC/scripts/setup_wsl2.sh"
    fi
else
    bad "node not found on PATH" \
        "install Node.js 18+: bash $SRC/scripts/setup_wsl2.sh"
fi

if command -v npm > /dev/null 2>&1; then
    ok "npm $(npm -v) ($(command -v npm))"
else
    bad "npm not found on PATH" \
        "install Node.js 18+: bash $SRC/scripts/setup_wsl2.sh"
fi

if command -v python3 > /dev/null 2>&1; then
    ok "python3 $(python3 -V 2>&1 | awk '{print $2}') ($(command -v python3))"
else
    bad "python3 not found on PATH" \
        "python3 is required by ROS 2 and by the prebuilt dashboard server"
fi

if command -v colcon > /dev/null 2>&1; then
    ok "colcon on PATH"
else
    warn "colcon not found on PATH" \
         "needed only to (re)build: bash $SRC/scripts/setup_wsl2.sh"
fi

# --------------------------------------------------------------------------
echo ""
echo "-- Workspace ($DEST) --"

if [ -d "$DEST" ]; then
    ok "workspace directory exists"
    if [ -f "$DEST/install/setup.bash" ]; then
        ok "workspace is built (install/setup.bash present)"
    else
        bad "workspace is not built ($DEST/install/setup.bash missing)" \
            "run: bash $SRC/scripts/sync_and_build.sh"
    fi
    for d in selene_sim selene_orchestrator selene_agent selene_hal selene_dashboard; do
        if [ -d "$DEST/$d" ]; then
            ok "$d present in workspace"
        else
            bad "$d missing from workspace" \
                "run: bash $SRC/scripts/sync_and_build.sh"
        fi
    done
else
    bad "workspace directory $DEST does not exist" \
        "run: bash $SRC/scripts/sync_and_build.sh"
fi

# --------------------------------------------------------------------------
echo ""
echo "-- Dashboard --"

# The workspace copy is what the launch files actually serve; the repo copy is
# what you edit. Report both, because rsync excludes node_modules and build.
for label_path in "workspace:$DEST/selene_dashboard" "repo:$SRC/selene_dashboard"; do
    label="${label_path%%:*}"
    dash="${label_path#*:}"
    if [ ! -d "$dash" ]; then
        [ "$label" = "workspace" ] && bad "$label dashboard dir missing ($dash)" \
            "run: bash $SRC/scripts/sync_and_build.sh"
        continue
    fi
    if [ -x "$dash/node_modules/.bin/react-scripts" ] || [ -f "$dash/node_modules/.bin/react-scripts" ]; then
        ok "$label node_modules installed (react-scripts present)"
    elif [ -d "$dash/node_modules" ]; then
        bad "$label node_modules exists but react-scripts is missing" \
            "run: cd $dash && npm install"
    else
        bad "$label node_modules missing" \
            "run: cd $dash && npm install   (or bash $SRC/scripts/sync_and_build.sh)"
    fi
    if [ -f "$dash/build/index.html" ]; then
        ok "$label production build present (fast demo path available)"
    else
        warn "$label production build missing ($dash/build/index.html)" \
             "run: cd $dash && npm run build   — otherwise the dev server must compile at launch (~minutes on WSL2)"
    fi
done

# --------------------------------------------------------------------------
echo ""
echo "-- World file --"

WORLD="$SRC/selene_sim/worlds/lunar_psr.sdf"
if [ -f "$WORLD" ]; then
    if command -v python3 > /dev/null 2>&1; then
        if python3 -c "import xml.etree.ElementTree as ET,sys; ET.parse(sys.argv[1])" "$WORLD" 2>/dev/null; then
            ok "lunar_psr.sdf parses as XML"
        else
            bad "lunar_psr.sdf is not valid XML" "fix $WORLD"
        fi
        GRAV=$(python3 - "$WORLD" <<'PY' 2>/dev/null
import sys, xml.etree.ElementTree as ET
w = ET.parse(sys.argv[1]).getroot().find('world')
g = w.find('gravity') if w is not None else None
print((g.text or '').strip() if g is not None else 'MISSING')
PY
)
        if [ "$GRAV" = "MISSING" ]; then
            bad "no world-scope <gravity> in lunar_psr.sdf" \
                "SDF ignores <gravity> nested in <physics>; the sim would run at Earth gravity"
        else
            ok "world-scope <gravity> = $GRAV"
            note "whether Gazebo honours it is NOT checked here (needs a real gz sim run)"
        fi
    else
        warn "cannot check lunar_psr.sdf (python3 unavailable)" "install python3"
    fi
else
    bad "world file missing ($WORLD)" "repo appears incomplete"
fi

# --------------------------------------------------------------------------
echo ""
echo "-- Ports --"

# Best-effort listener detection: prefer ss, then lsof, then bash /dev/tcp.
port_in_use() {
    local port=$1
    if command -v ss > /dev/null 2>&1; then
        ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${port}\$" && return 0
        return 1
    fi
    if command -v lsof > /dev/null 2>&1; then
        lsof -iTCP:"$port" -sTCP:LISTEN -n -P > /dev/null 2>&1 && return 0
        return 1
    fi
    # Fallback: something answering a connect() means the port is taken.
    (echo > "/dev/tcp/127.0.0.1/$port") 2>/dev/null && return 0
    return 1
}

if command -v ss > /dev/null 2>&1 || command -v lsof > /dev/null 2>&1; then
    PORT_METHOD="listener table"
else
    PORT_METHOD="connect probe (less reliable: cannot see listeners bound only to other interfaces)"
fi
echo "  (detection method: $PORT_METHOD)"

for spec in "3000:dashboard:pkill -f react-scripts ; pkill -f 'http.server 3000'" \
            "9090:rosbridge:pkill -f rosbridge"; do
    port="${spec%%:*}"
    rest="${spec#*:}"
    who="${rest%%:*}"
    hint="${rest#*:}"
    if port_in_use "$port"; then
        bad "port $port ($who) is already in use" \
            "find the owner (ss -ltnp | grep :$port) and stop it, e.g.: $hint"
    else
        ok "port $port ($who) is free"
    fi
done

# --------------------------------------------------------------------------
echo ""
echo "============================================"
echo " Summary: $PASS ok, $FAIL failed, $WARN warnings"
if [ "$FAIL" -gt 0 ]; then
    echo ""
    echo " Blocking problems:"
    for i in "${FAILED_ITEMS[@]}"; do echo "   - $i"; done
fi
if [ "$WARN" -gt 0 ]; then
    echo ""
    echo " Non-blocking warnings:"
    for i in "${WARNED_ITEMS[@]}"; do echo "   - $i"; done
fi
echo ""
echo " Not covered by this script: Gazebo actually starting, ROS 2 DDS"
echo " discovery, node startup, dashboard<->rosbridge connectivity, robot"
echo " motion, and whether lunar gravity takes effect in Gazebo."
echo "============================================"

[ "$FAIL" -gt 0 ] && exit 1
exit 0
