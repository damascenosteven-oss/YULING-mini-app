import type { Metadata } from 'next';
import ModelSettings from '@/components/ppt/model-settings';

export const metadata: Metadata = { title: '模型设置 · 毓灵 AI PPT' };

export default function SettingsPage() { return <ModelSettings />; }
