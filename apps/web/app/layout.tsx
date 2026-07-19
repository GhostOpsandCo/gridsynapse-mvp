import type { Metadata } from "next";
import "./globals.css";

const siteUrl = "https://gridsynapse.vercel.app";

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: {
    default: "GridSynapse | AI Compute Optimization",
    template: "%s | GridSynapse",
  },
  description:
    "Compare and validate GPU workload placements across cost, carbon, delay, and capacity risk with an auditable operator workflow.",
  applicationName: "GridSynapse",
  alternates: {
    canonical: "/",
  },
  openGraph: {
    type: "website",
    url: "/",
    siteName: "GridSynapse",
    title: "GridSynapse | AI Compute Optimization",
    description:
      "Compare and validate GPU workload placements across cost, carbon, delay, and capacity risk.",
  },
  twitter: {
    card: "summary_large_image",
    title: "GridSynapse | AI Compute Optimization",
    description:
      "Compare and validate GPU workload placements across cost, carbon, delay, and capacity risk.",
  },
  robots: {
    index: true,
    follow: true,
  },
};

const softwareApplicationSchema = {
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  name: "GridSynapse",
  url: siteUrl,
  applicationCategory: "BusinessApplication",
  operatingSystem: "Web",
  description:
    "An operator-facing console for comparing and validating GPU workload placements across cost, carbon, delay, and capacity risk.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{
            __html: JSON.stringify(softwareApplicationSchema).replace(/</g, "\\u003c"),
          }}
        />
        {children}
      </body>
    </html>
  );
}
