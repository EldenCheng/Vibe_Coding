#!/usr/bin/env python3
import json
import shutil
import os
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

class SceneGenerator:
    def __init__(self, source_dir: str, output_dir: str, scene_id: str, grade_level: str):
        self.source_dir = Path(source_dir)
        self.output_dir = Path(output_dir)
        self.scene_id = scene_id
        self.grade_level = grade_level
        self.scene_dir = self.output_dir / scene_id

    def parse_questions(self, questions_file: str) -> List[Dict[str, any]]:
        """解析questions.txt文件，提取问题列表"""
        questions = []
        with open(self.source_dir / questions_file, 'r', encoding='utf-8') as f:
            content = f.read()
            # 按问题编号分割
            parts = content.split('第')
            for i, part in enumerate(parts[1:], 1):  # 跳过第一部分（通常是空的）
                if ':' in part:
                    # 提取问题文本
                    question_text = part.split(':', 1)[1].strip()
                    if question_text:
                        questions.append({
                            "id": f"q{i}",
                            "text": question_text,
                            "order": i
                        })
        return questions

    def generate_meta_json(self, title: str, image_alt: str, image_description: str) -> Dict[str, str]:
        """生成meta.json内容"""
        return {
            "id": self.scene_id,
            "title": title,
            "gradeLevel": self.grade_level,
            "imageAlt": image_alt,
            "imageDescription": image_description,
            "createdAt": datetime.now().strftime("%Y-%m-%d")
        }

    def generate_index_json(self, existing_scenes: Optional[List[str]] = None) -> Dict[str, List[str]]:
        """生成或更新index.json"""
        index_file = self.output_dir / "index.json"
        
        if existing_scenes is None and index_file.exists():
            with open(index_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                existing_scenes = data.get("scenes", [])
        
        if existing_scenes is None:
            existing_scenes = []
        
        # 添加新场景（如果不存在）
        if self.scene_id not in existing_scenes:
            existing_scenes.append(self.scene_id)
        
        return {"scenes": existing_scenes}

    def copy_image(self, image_file: str, target_name: str = "image.jpg") -> Path:
        """复制图片到场景目录"""
        source_image = self.source_dir / image_file
        target_image = self.scene_dir / target_name
        
        if not source_image.exists():
            raise FileNotFoundError(f"Source image not found: {source_image}")
        
        shutil.copy2(source_image, target_image)
        return target_image

    def generate_scene(self, questions_file: str = "questions.txt", 
                       image_file: str = "Market.jpg",
                       title: Optional[str] = None,
                       image_alt: Optional[str] = None,
                       image_description: Optional[str] = None,
                       overwrite: bool = False) -> None:
        """生成完整的场景数据"""
        
        # 检查源文件
        if not (self.source_dir / questions_file).exists():
            raise FileNotFoundError(f"Questions file not found: {self.source_dir / questions_file}")
        
        # 创建场景目录
        if self.scene_dir.exists():
            if not overwrite:
                raise FileExistsError(f"Scene directory already exists: {self.scene_dir}. Use overwrite=True to replace.")
            shutil.rmtree(self.scene_dir)
        self.scene_dir.mkdir(parents=True, exist_ok=True)
        
        # 解析问题
        questions = self.parse_questions(questions_file)
        if not questions:
            raise ValueError("No valid questions found in questions.txt")
        
        # 生成或更新index.json
        index_data = self.generate_index_json()
        with open(self.output_dir / "index.json", 'w', encoding='utf-8') as f:
            json.dump(index_data, f, indent=2, ensure_ascii=False)
        
        # 设置默认值
        if title is None:
            title = self.scene_id.replace('_', ' ').title()
        if image_alt is None:
            image_alt = f"A scene from {title}"
        if image_description is None:
            # 从第一个问题中推断描述
            image_description = f"A scene depicting {title.lower()} for English practice."
        
        # 生成meta.json
        meta_data = self.generate_meta_json(title, image_alt, image_description)
        with open(self.scene_dir / "meta.json", 'w', encoding='utf-8') as f:
            json.dump(meta_data, f, indent=2, ensure_ascii=False)
        
        # 复制图片
        self.copy_image(image_file)
        
        # 生成questions.json
        questions_data = {"questions": questions}
        with open(self.scene_dir / "questions.json", 'w', encoding='utf-8') as f:
            json.dump(questions_data, f, indent=2, ensure_ascii=False)
        
        print(f"[OK] Scene generated successfully: {self.scene_id}")
        print(f"  - Location: {self.scene_dir.absolute()}")
        print(f"  - Questions: {len(questions)}")
        print(f"  - Grade Level: {self.grade_level}")
        print()


def main():
    # 配置
    source_dir = "../resources/test_sc01"
    output_dir = "../demo/assets/scenes"
    scene_id = "junior_market"
    grade_level = "junior"
    
    # 生成场景
    generator = SceneGenerator(source_dir, output_dir, scene_id, grade_level)
    generator.generate_scene(
        questions_file="questions.txt",
        image_file="Market.jpg",
        title="A Visit to the Street Market",
        image_alt="A busy street market with vendors selling fresh fruits and vegetables",
        image_description="A bustling street market scene. Local vendors are selling fresh produce including dragon fruit, oranges, and other fruits. Students are browsing the market, with Li Wei recommending a snack to Sarah. The atmosphere is lively and colorful.",
        overwrite=True
    )


if __name__ == "__main__":
    main()