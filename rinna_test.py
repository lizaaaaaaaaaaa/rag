from transformers import AutoTokenizer, AutoModelForCausalLM, pipeline

model_id = "rinna/japanese-gpt-neox-3.6b-instruction-ppo"

# トークナイザーとモデルの読み込み
tokenizer = AutoTokenizer.from_pretrained(model_id, use_fast=False)
model = AutoModelForCausalLM.from_pretrained(model_id)

# 推論用のパイプラインを作成
generator = pipeline("text-generation", model=model, tokenizer=tokenizer)

# 質問を送ってみる
input_text = "以下の質問に日本語で丁寧に答えてください：日本語のRAGシステムとは何ですか？"
output = generator(input_text, max_new_tokens=100, do_sample=True)

# 結果を表示
print("🧠 回答:", output[0]["generated_text"])
