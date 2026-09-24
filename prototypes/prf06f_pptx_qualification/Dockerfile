FROM node:22.16.0-bookworm-slim
WORKDIR /qualification
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts --no-audit --no-fund
COPY qualify.mjs ./
RUN useradd --create-home qualifier && mkdir /output && chown qualifier:qualifier /output
USER qualifier
CMD ["node", "qualify.mjs", "/output"]
