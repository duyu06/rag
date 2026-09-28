#!/usr/bin/env bash
# B0-T5 Step 3.5 —— 容器内 3.12 那一格（规格 §8.2 / B0-15）的准备段。
# 用的是**发布镜像** rag-backend:security-a-rc1：`python -V` 实测 Python 3.12.14，
# 且 15 条 backend/requirements.txt 的包全部在场（含 torch 2.14.0+cpu）——
# 这正是规格 §8.2 点名的"SEC-A 容器基准实测所用量测环境"，比重新 pip 装一遍整份依赖更接近 CI，
# 也不依赖下载 torch 的那几百 MB。
#
# 形态刻意对齐 CI：
#   cwd = /w（仓库根）、`python -m pytest backend/tests -q`、**没有 backend/.env**
#   —— 树是照 `git ls-files --cached --others --exclude-standard`（= SECA-20 的交付面定义，318 枚）
#      打进容器自己的文件系统，`.env` 被 .gitignore 挡在面外 ⇒ 天然不在场（与 CI checkout 同构）。
#   刻意不用 bind mount：Windows 的挂载会**真的**把容器里的写落到宿主工作树（含 `rm backend/.env`
#   这种必须发生的形态动作），一次误删就是宿主 `.env` 没了 —— 卡 F 那一族的失效面。
set -eu
T="$(pwd -W)"
STAGE_DIR="$(mktemp -d)"          # 树外暂存（不往仓库里落副本，卡 F）
echo "repo root : $T"
echo "stage dir : $STAGE_DIR"

# --- 1) 打包交付面 + .git（.git 只有 4MB，容器里的门要跑 `git ls-files` 系列就得有仓） ---
git -c core.quotePath=false ls-files -z --cached --others --exclude-standard > "$STAGE_DIR/surface.list"
echo "surface files packed: $(tr -d -c '\0' < "$STAGE_DIR/surface.list" | wc -c)"
tar --null -cf "$STAGE_DIR/surface.tar" -T "$STAGE_DIR/surface.list"
tar -cf "$STAGE_DIR/gitdir.tar" .git
ls -la "$STAGE_DIR"

NAME="${DOCKER_NAME:-b0-t5-cell}"
docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" rag-backend:security-a-rc1 sleep 3600 >/dev/null
echo "container started: $NAME"

docker cp "$STAGE_DIR/surface.tar" "$NAME:/tmp/surface.tar"
docker cp "$STAGE_DIR/gitdir.tar"  "$NAME:/tmp/gitdir.tar"
docker exec "$NAME" sh -lc 'mkdir -p /w && tar -xf /tmp/surface.tar -C /w && tar -xf /tmp/gitdir.tar -C /w && rm -f /tmp/surface.tar /tmp/gitdir.tar'
echo "--- /w top-level in container ---"
docker exec -w /w "$NAME" sh -lc 'ls -a /w | head -20; echo "backend/.env present? $([ -f /w/backend/.env ] && echo YES-FATAL || echo no)"'
echo "--- git works in container? ---"
docker exec "$NAME" sh -lc 'git config --global --add safe.directory /w || true'
docker exec -w /w "$NAME" sh -lc 'git rev-parse HEAD; git ls-files --cached | wc -l; git ls-files --others --exclude-standard | wc -l'
echo "--- install pytest (CI 装清单的第 3 行；apt/pip 走网络，实测可达) ---"
docker exec "$NAME" python -m pip install --disable-pip-version-check --quiet pytest
docker exec "$NAME" python -m pytest --version
echo "$STAGE_DIR" > /tmp/b0_t5_container_stage.txt
echo "READY: docker exec -w /w $NAME python -m pytest backend/tests -q"
