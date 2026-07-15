import fitz  # PyMuPDF
import os
import sys

def extract_pdf_content(pdf_path):
    if not os.path.exists(pdf_path):
        print(f"Error: File {pdf_path} not found.")
        return

    base_name = os.path.splitext(os.path.basename(pdf_path))[0]
    output_dir = f"{base_name}_extracted"
    os.makedirs(output_dir, exist_ok=True)

    doc = fitz.open(pdf_path)
    
    # 1. Extract Text
    text_path = os.path.join(output_dir, "extracted_text.txt")
    with open(text_path, "w", encoding="utf-8") as text_file:
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            text_file.write(f"--- Page {page_num + 1} ---\n")
            text_file.write(page.get_text())
            text_file.write("\n\n")
    print(f"Text extracted to: {text_path}")

    # 2. Extract Images
    image_dir = os.path.join(output_dir, "images")
    os.makedirs(image_dir, exist_ok=True)
    
    image_count = 0
    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        image_list = page.get_images(full=True)

        for img_index, img in enumerate(image_list):
            xref = img[0]
            base_image = doc.extract_image(xref)
            image_bytes = base_image["image"]
            image_ext = base_image["ext"]
            
            image_filename = f"page{page_num+1}_img{img_index+1}.{image_ext}"
            image_path = os.path.join(image_dir, image_filename)
            
            with open(image_path, "wb") as f:
                f.write(image_bytes)
            image_count += 1

    print(f"Extracted {image_count} images to: {image_dir}")
    doc.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python pdf_extractor.py <path_to_pdf>")
    else:
        extract_pdf_content(sys.argv[1])
