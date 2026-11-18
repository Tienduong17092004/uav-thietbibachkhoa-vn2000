FROM python:3.11-slim

WORKDIR /app

COPY uav_app /app/uav_app
COPY config/agent_model_tiers.json config/cloudflared_thietbibachkhoa.yml config/uav_keys_google_sheet.csv /app/config/
COPY deploy /app/deploy
COPY scripts /app/scripts
COPY MO_WEB_NHAN_DIEN_NGAY.html AGENTS.md MODEL_TIERS_POLICY.md DOMAIN_SETUP_THIETBIBACHKHOA.md TPU_OFFLOAD_ULTRA_GUIDE.md HUONG_DAN_VUOT_TUONG_LUA_THIETBIBACHKHOA.md /app/

ENV HOST=0.0.0.0
ENV UAV_WEB_PORT=7860
ENV PORT=7860
ENV UAV_DATA_DIR=/app/data
RUN mkdir -p /app/data && chmod 777 /app/data

EXPOSE 7860

CMD ["python3", "-m", "uav_app.adapters.webgpu_public_server", "--host", "0.0.0.0"]
