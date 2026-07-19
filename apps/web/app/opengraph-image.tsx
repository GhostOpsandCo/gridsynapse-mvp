import { ImageResponse } from "next/og";

export const alt = "GridSynapse AI compute optimization console";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpenGraphImage() {
  return new ImageResponse(
    <div
      style={{
        alignItems: "center",
        background: "linear-gradient(135deg, #07111f 0%, #12334f 100%)",
        color: "#f4f7fb",
        display: "flex",
        height: "100%",
        justifyContent: "center",
        padding: "80px",
        width: "100%",
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 24, maxWidth: 1000 }}>
        <div style={{ color: "#7de3c3", display: "flex", fontSize: 30, letterSpacing: 3 }}>
          GRIDSYNAPSE
        </div>
        <div style={{ display: "flex", fontSize: 72, fontWeight: 700, lineHeight: 1.05 }}>
          Auditable AI compute optimization
        </div>
        <div style={{ color: "#c2d1df", display: "flex", fontSize: 32 }}>
          Compare cost, carbon, delay, and capacity risk before approving a placement.
        </div>
      </div>
    </div>,
    size,
  );
}
