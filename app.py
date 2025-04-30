from fastapi import FastAPI, HTTPException, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy import Column, Integer, String, Float, Boolean, JSON, ForeignKey, select, Text
from pathlib import Path
from datetime import datetime, timezone
import json, logging, asyncio
from contextlib import asynccontextmanager
from typing import List, Dict, Any

DATABASE_URL = "sqlite+aiosqlite:///./products.db"
engine = create_async_engine(
    DATABASE_URL,
    echo=True,
    json_serializer=lambda x: json.dumps(x, ensure_ascii=False),
    json_deserializer=json.loads
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)
Base = declarative_base()

DATA_FILE = Path("products.json")

# إعداد نظام التسجيل (Logging)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # إنشاء الجداول عند بدء التشغيل
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # تحميل البيانات من ملف JSON إذا كانت قاعدة البيانات فارغة
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Product))
        products = result.scalars().all()
        
        if not products and DATA_FILE.exists():
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as file:
                    data = json.load(file)
                    for category, items in data.items():
                        for item in items:
                            item["category"] = category
                            session.add(Product(**item))
                    await session.commit()
                logger.info("✅ Database populated from JSON file.")
            except Exception as e:
                logger.error(f"❌ Error loading data from JSON: {str(e)}")
                await session.rollback()
    
    yield
    
    # تنظيف عند إيقاف التطبيق
    await engine.dispose()

app = FastAPI(lifespan=lifespan)

class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True, index=True)
    category = Column(String, index=True)
    title = Column(String)
    description = Column(Text)
    brand = Column(String)
    sku = Column(String)
    price = Column(Float)
    discountPercentage = Column(Float)
    rating = Column(Float)
    stock = Column(Integer)
    weight = Column(Integer) 
    dimensions = Column(JSON)
    warrantyInformation = Column(String)
    shippingInformation = Column(String)
    availabilityStatus = Column(String)
    returnPolicy = Column(String)
    minimumOrderQuantity = Column(Integer)
    meta = Column(JSON) 
    tags = Column(JSON)  
    images = Column(JSON)  
    thumbnail = Column(String)
    reviews = Column(JSON, nullable=False, server_default='[]')  # تم التعديل هنا

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info(f"Incoming request: {request.method} {request.url}")
    response = await call_next(request)
    return response

@app.get("/products/{category}")
async def get_products(category: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Product).where(Product.category == category))
    products = result.scalars().all()
    if not products:
        raise HTTPException(status_code=404, detail=f"No products found in category {category}")
    return {category: [p.__dict__ for p in products]}

@app.get("/products/{category}/{product_id}")
async def get_single_product(
    category: str, 
    product_id: int, 
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Product).where(Product.id == product_id, Product.category == category)
    )
    product = result.scalar_one_or_none()
    
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    # تحويل النتيجة إلى dictionary مع معالجة الـ reviews
    product_dict = product.__dict__
    product_dict['reviews'] = product.reviews if product.reviews else []
    return product_dict

@app.post("/products/{category}/{product_id}/reviews")
async def add_review(
    category: str, 
    product_id: int,
    review: dict, 
    db: AsyncSession = Depends(get_db)
):
    logger.info(f"Adding review to product {product_id} in category {category}")
    logger.info(f"Review data: {review}")

    result = await db.execute(
        select(Product).where(Product.id == product_id, Product.category == category)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    logger.info(f"Current reviews before update: {product.reviews}")

    review["date"] = datetime.now(timezone.utc).isoformat(timespec="milliseconds")

    current_reviews = product.reviews if product.reviews else []
    updated_reviews = current_reviews.copy()
    updated_reviews.append(review)

    # ✅ تحديث الـ reviews
    product.reviews = updated_reviews

    # ✅ حساب متوسط التقييم الجديد
    ratings = [r.get("rating", 0) for r in updated_reviews if isinstance(r.get("rating", 0), (int, float))]
    avg_rating = sum(ratings) / len(ratings) if ratings else 0.0
    product.rating = round(avg_rating, 2)  # تخلي الرقم بدقة منزلتين عشريتين

    logger.info(f"Updated rating: {product.rating}")
    logger.info(f"Reviews after update: {product.reviews}")

    try:
        await db.commit()
        await db.refresh(product)
        logger.info("✅ Review added and rating updated")
        return {
            "message": "Review added and rating updated",
            "review": review,
            "new_rating": product.rating
        }
    except Exception as e:
        await db.rollback()
        logger.error(f"❌ Error adding review: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to add review")


with open("categories.json", "r") as f:
    categories = json.load(f)

@app.get("/category/{category_name}")
def get_category_items(category_name: str): 
    category_name = category_name.lower()

    if category_name not in categories:
        raise HTTPException(status_code=404, detail="Category not found")

    return {
        "category": category_name,
        "items": categories[category_name]
    }


