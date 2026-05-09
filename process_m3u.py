#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CCTV M3U 后处理脚本
功能：
1. 读取原始 cctv_live.m3u
2. 按频道名称排序（CCTV-1 到 CCTV-17）
3. 按清晰度排序（4K > 1080p > 720p > 480p > 360p > 270p）
4. 生成标准格式的 M3U 文件，相同频道使用相同 tvg-id 和 tvg-name
   使播放器识别为同一频道的多个源（自动清晰度切换）
"""

import re
import os
import ast
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class StreamSource:
    """单个直播源"""
    url: str
    resolution: int = 0
    resolution_label: str = ""

    def __post_init__(self):
        if not self.resolution_label and self.resolution:
            self.resolution_label = f"{self.resolution}p"


@dataclass
class Channel:
    """频道对象"""
    name: str
    display_name: str
    sources: List[StreamSource] = field(default_factory=list)

    @property
    def sort_key(self) -> tuple:
        """生成排序用的 key"""
        num_match = re.search(r'(\d+)', self.name)
        if num_match:
            num = int(num_match.group(1))
            if '4k' in self.name.lower():
                return (0, 0)
            return (1, num)
        return (2, 0)


def extract_resolution(url: str) -> tuple[int, str]:
    """从 URL 中提取清晰度信息"""
    url_lower = url.lower()

    if any(x in url_lower for x in ['4k', '2160p', '2160', 'uhd']):
        return (2160, "4K")
    if any(x in url_lower for x in ['1080p', '1080', 'fhd', '1920x1080']):
        return (1080, "1080p")
    if any(x in url_lower for x in ['720p', '720', 'hd', '1280x720']):
        return (720, "720p")
    if any(x in url_lower for x in ['480p', '480', 'sd', '854x480', '640x480']):
        return (480, "480p")
    if any(x in url_lower for x in ['360p', '360', '640x360']):
        return (360, "360p")
    if any(x in url_lower for x in ['270p', '270', '240p', '240', '480x270']):
        return (270, "270p")

    patterns = [
        r'[/._-](\d{3,4})p[/._-]?',
        r'[/._-](\d{3,4})[/._-]?',
        r'_(\d{3,4})_',
        r'[/](\d{3,4})[/]',
    ]
    for pattern in patterns:
        match = re.search(pattern, url_lower)
        if match:
            res_val = int(match.group(1))
            if res_val >= 2000: return (1080, "1080p")
            elif res_val >= 1000: return (720, "720p")
            elif res_val >= 600: return (480, "480p")
            elif res_val >= 400: return (360, "360p")
            else: return (res_val, f"{res_val}p")

    # 从 mhd/mbd/mud 推断
    if '_mhd.' in url_lower:
        return (720, "720p")
    elif '_mbd.' in url_lower:
        return (480, "480p")
    elif '_mud.' in url_lower:
        return (360, "360p")

    return (1080, "1080p")


def parse_url_line(line: str) -> List[str]:
    """
    解析 URL 行，支持多种格式：
    1. 单个 URL: https://...
    2. Python 列表: ['url1', 'url2', ...]
    3. 逗号分隔: url1,url2
    """
    line = line.strip()
    if not line or line.startswith('#'):
        return []

    # 尝试解析 Python 列表格式
    if line.startswith("[") and line.endswith("]"):
        try:
            urls = ast.literal_eval(line)
            if isinstance(urls, list):
                return [str(u).strip() for u in urls if str(u).strip().startswith('http')]
        except (SyntaxError, ValueError):
            pass

    # 单个 URL
    if line.startswith('http'):
        return [line]

    return []


def parse_original_m3u(filepath: str) -> List[Channel]:
    """解析原始 M3U 文件"""
    channels = []

    if not os.path.exists(filepath):
        print(f"⚠️ 文件不存在: {filepath}")
        return channels

    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if not line or (line.startswith('#') and not line.startswith('#EXTINF')):
            i += 1
            continue

        if line.startswith('#EXTINF'):
            extinf = line
            i += 1
            if i >= len(lines):
                break

            # 解析 URL 行（支持列表格式）
            url_line = lines[i].strip()
            urls = parse_url_line(url_line)

            if not urls:
                i += 1
                continue

            # 提取显示名称
            name_match = re.search(r',(.+)$', extinf)
            display_name = name_match.group(1).strip() if name_match else "Unknown"
            # 去掉清晰度标注
            display_name = re.sub(r'\s*\(.*?\)$', '', display_name).strip()

            # 提取 tvg-id
            id_match = re.search(r'tvg-id="([^"]+)"', extinf)
            name = id_match.group(1) if id_match else display_name.lower().replace('-', '').replace(' ', '')

            existing = next((c for c in channels if c.name == name), None)
            if not existing:
                existing = Channel(name=name, display_name=display_name)
                channels.append(existing)

            for url in urls:
                res_val, res_label = extract_resolution(url)
                source = StreamSource(url=url, resolution=res_val, resolution_label=res_label)
                existing.sources.append(source)

        elif ',' in line and not line.startswith('#') and not line.startswith('['):
            # 简单格式: 频道名,http://...
            parts = line.split(',', 1)
            if len(parts) == 2 and parts[1].strip().startswith('http'):
                display_name = parts[0].strip()
                url = parts[1].strip()
                name = display_name.lower().replace('-', '').replace(' ', '')

                existing = next((c for c in channels if c.name == name), None)
                if not existing:
                    existing = Channel(name=name, display_name=display_name)
                    channels.append(existing)

                res_val, res_label = extract_resolution(url)
                source = StreamSource(url=url, resolution=res_val, resolution_label=res_label)
                existing.sources.append(source)

        i += 1

    return channels


def sort_and_deduplicate(channels: List[Channel]) -> List[Channel]:
    """排序频道和源，去重"""
    channels.sort(key=lambda c: c.sort_key)

    for channel in channels:
        # 按清晰度降序排列
        channel.sources.sort(key=lambda s: s.resolution, reverse=True)

        # 去重：相同清晰度只保留第一个，相同URL只保留一个
        seen_resolutions = set()
        seen_urls = set()
        unique_sources = []

        for source in channel.sources:
            # 规范化URL用于去重（去掉auth_key参数）
            norm_url = re.sub(r'\?auth_key=[^&]*', '', source.url)

            if source.resolution not in seen_resolutions and norm_url not in seen_urls:
                seen_resolutions.add(source.resolution)
                seen_urls.add(norm_url)
                unique_sources.append(source)

        channel.sources = unique_sources

    return channels


def generate_standard_m3u(channels: List[Channel], output_file: str = "cctv_live_sorted.m3u"):
    """
    生成标准 M3U 文件
    关键：相同频道的所有源使用相同的 tvg-id 和 tvg-name
    """
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("#EXTM3U\n")
        f.write("# Generated by CCTV Live Scraper + Post Processor\n")
        f.write("# Sorted by channel name (ascending) and resolution (descending)\n")
        f.write("# Same tvg-id/tvg-name for multi-quality streams (player auto-select)\n\n")

        success_count = 0
        total_sources = 0

        for channel in channels:
            if not channel.sources:
                continue

            success_count += 1

            for source in channel.sources:
                # 关键：所有源使用相同的 tvg-id 和 tvg-name
                f.write(f'#EXTINF:-1 tvg-id="{channel.name}" '
                       f'tvg-name="{channel.display_name}" '
                       f'group-title="CCTV",'
                       f'{channel.display_name} ({source.resolution_label})\n')

                f.write(f"{source.url}\n\n")
                total_sources += 1

        f.write(f"# Total channels: {success_count}\n")
        f.write(f"# Total sources: {total_sources}\n")

    print(f"\n🎉 标准 M3U 文件生成完成！")
    print(f"📁 文件保存为: {output_file}")
    print(f"📊 共 {success_count} 个频道，{total_sources} 个源")

    return output_file


def print_summary(channels: List[Channel]):
    """打印处理摘要"""
    print("\n" + "=" * 70)
    print("📊 处理结果汇总")
    print("=" * 70)

    for channel in channels:
        if not channel.sources:
            print(f"❌ {channel.display_name:15} → 无可用源")
            continue

        sources_info = ", ".join([f"{s.resolution_label}" for s in channel.sources])
        print(f"✅ {channel.display_name:15} → {len(channel.sources)} 个源 [{sources_info}]")


def main():
    input_file = "cctv_live.m3u"
    output_file = "cctv_live_sorted.m3u"

    print(f"🚀 开始处理 M3U 文件...")
    print(f"📥 输入文件: {input_file}")

    channels = parse_original_m3u(input_file)
    print(f"📋 解析到 {len(channels)} 个频道")

    channels = sort_and_deduplicate(channels)

    generate_standard_m3u(channels, output_file)

    print_summary(channels)

    # 替换原文件
    if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
        backup_file = "cctv_live_backup.m3u"
        if os.path.exists(input_file):
            os.rename(input_file, backup_file)
            print(f"💾 原文件已备份为: {backup_file}")

        os.rename(output_file, input_file)
        print(f"✅ 已替换原文件: {input_file}")

    return channels


if __name__ == "__main__":
    main()
