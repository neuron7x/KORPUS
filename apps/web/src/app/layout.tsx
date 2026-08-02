import type { Metadata, Viewport } from "next";
import "./styles.css";

export const metadata: Metadata = {
  title: "КОРПУС",
  description: "Доказова довідкова та навчальна система",
  manifest: "/manifest.webmanifest",
};

export const viewport: Viewport = { themeColor: "#111711", colorScheme: "dark" };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="uk">
      <body>{children}</body>
    </html>
  );
}

