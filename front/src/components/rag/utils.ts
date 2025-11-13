export const session: any = {
  accessToken: import.meta.env?.VITE_LANGCONNECT_API_SECRET_TOKEN,
};

export const LANGCONNECT_API_URL: string | undefined = import.meta.env
  ?.VITE_LANGCONNECT_API_URL;

export const MCP_PROXY_URL: string | undefined = import.meta.env
  ?.VITE_MCP_PROXY_URL;

export const ragEnabled = () => {
  return !!session.accessToken && !!LANGCONNECT_API_URL;
};
