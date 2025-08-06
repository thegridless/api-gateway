from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import httpx
import asyncio
import json
import time
from typing import Dict, List, Optional, Any
import uvicorn

app = FastAPI(title="Custom API Gateway", version="1.0.0")

# Модели данных
class ServiceConfig(BaseModel):
    url: str
    timeout: int = 5
    enabled: bool = True
    headers: Dict[str, str] = {}

class OrderRequest(BaseModel):
    order_id: str

class ServiceResponse(BaseModel):
    service: str
    data: Optional[Any] = None
    error: Optional[str] = None
    response_time: float

class MergedResponse(BaseModel):
    order_id: str
    services: List[ServiceResponse]
    timestamp: float
    total_time: float

# Глобальная конфигурация сервисов
services_config: Dict[str, ServiceConfig] = {
    "service1": ServiceConfig(
        url="http://service1:8080",
        timeout=5,
        enabled=True
    ),
    "service2": ServiceConfig(
        url="http://service2:8080", 
        timeout=5,
        enabled=True
    )
}

# Основной endpoint для обработки заказов
@app.post("/api/order", response_model=MergedResponse)
async def handle_order(request: OrderRequest):
    start_time = time.time()
    
    # Определяем какие сервисы вызывать
    services_to_call = determine_services(request.order_id)
    
    # Параллельно вызываем сервисы
    responses = await call_services_parallel(request.order_id, services_to_call)
    
    total_time = time.time() - start_time
    
    return MergedResponse(
        order_id=request.order_id,
        services=responses,
        timestamp=time.time(),
        total_time=total_time
    )

def determine_services(order_id: str) -> List[str]:
    """Определяет какие сервисы нужно вызвать на основе бизнес-логики"""
    # Здесь можно добавить логику на основе order_id
    # Например, четные ID идут в service1, нечетные в оба сервиса
    
    enabled_services = [
        name for name, config in services_config.items() 
        if config.enabled
    ]
    
    # Пример бизнес-логики
    if int(order_id) % 2 == 0:
        return ["service1"]  # Только первый сервис
    else:
        return enabled_services  # Все включенные сервисы

async def call_services_parallel(order_id: str, services: List[str]) -> List[ServiceResponse]:
    """Параллельно вызывает указанные сервисы"""
    tasks = [call_service(order_id, service_name) for service_name in services]
    return await asyncio.gather(*tasks)

async def call_service(order_id: str, service_name: str) -> ServiceResponse:
    """Вызывает отдельный сервис"""
    start_time = time.time()
    
    if service_name not in services_config:
        return ServiceResponse(
            service=service_name,
            error="Service not configured",
            response_time=0
        )
    
    config = services_config[service_name]
    url = f"{config.url}/order/{order_id}"
    
    try:
        async with httpx.AsyncClient(timeout=config.timeout) as client:
            response = await client.get(url, headers=config.headers)
            response.raise_for_status()
            
            response_time = time.time() - start_time
            
            return ServiceResponse(
                service=service_name,
                data=response.json(),
                response_time=response_time
            )
            
    except httpx.TimeoutException:
        return ServiceResponse(
            service=service_name,
            error="Timeout",
            response_time=time.time() - start_time
        )
    except httpx.HTTPStatusError as e:
        return ServiceResponse(
            service=service_name,
            error=f"HTTP {e.response.status_code}",
            response_time=time.time() - start_time
        )
    except Exception as e:
        return ServiceResponse(
            service=service_name,
            error=str(e),
            response_time=time.time() - start_time
        )

# API для управления конфигурацией
@app.get("/admin/config")
async def get_config():
    return services_config

@app.put("/admin/config")
async def update_config(new_config: Dict[str, ServiceConfig]):
    global services_config
    services_config = new_config
    return {"status": "updated", "config": services_config}

@app.post("/admin/config/{service_name}")
async def add_service(service_name: str, config: ServiceConfig):
    services_config[service_name] = config
    return {"status": "added", "service": service_name}

@app.delete("/admin/config/{service_name}")
async def remove_service(service_name: str):
    if service_name in services_config:
        del services_config[service_name]
        return {"status": "removed", "service": service_name}
    raise HTTPException(status_code=404, detail="Service not found")

# Статические файлы для UI
app.mount("/static", StaticFiles(directory="static"), name="static")

# UI Dashboard
@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>API Gateway Dashboard</title>
        <script src="https://unpkg.com/vue@3/dist/vue.global.js"></script>
        <script src="https://unpkg.com/axios/dist/axios.min.js"></script>
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; }
            .container { max-width: 1200px; margin: 0 auto; }
            .service-card { border: 1px solid #ddd; padding: 15px; margin: 10px 0; border-radius: 5px; }
            .enabled { background-color: #e8f5e8; }
            .disabled { background-color: #ffe8e8; }
            .form-group { margin: 10px 0; }
            .form-group label { display: block; margin-bottom: 5px; }
            .form-group input, .form-group select { width: 100%; padding: 8px; }
            .btn { padding: 10px 15px; margin: 5px; border: none; border-radius: 3px; cursor: pointer; }
            .btn-primary { background-color: #007bff; color: white; }
            .btn-danger { background-color: #dc3545; color: white; }
            .btn-success { background-color: #28a745; color: white; }
            .test-section { margin-top: 30px; padding: 20px; background-color: #f8f9fa; border-radius: 5px; }
        </style>
    </head>
    <body>
        <div id="app" class="container">
            <h1>API Gateway Dashboard</h1>
            
            <!-- Services Configuration -->
            <h2>Services Configuration</h2>
            <div v-for="(service, name) in services" :key="name" 
                 :class="['service-card', service.enabled ? 'enabled' : 'disabled']">
                <h3>{{ name }}</h3>
                <div class="form-group">
                    <label>URL:</label>
                    <input v-model="service.url" type="text">
                </div>
                <div class="form-group">
                    <label>Timeout (seconds):</label>
                    <input v-model.number="service.timeout" type="number">
                </div>
                <div class="form-group">
                    <label>Enabled:</label>
                    <select v-model="service.enabled">
                        <option :value="true">Yes</option>
                        <option :value="false">No</option>
                    </select>
                </div>
                <button @click="removeService(name)" class="btn btn-danger">Remove</button>
            </div>
            
            <button @click="saveConfig" class="btn btn-primary">Save Configuration</button>
            
            <!-- Add New Service -->
            <h3>Add New Service</h3>
            <div class="service-card">
                <div class="form-group">
                    <label>Service Name:</label>
                    <input v-model="newService.name" type="text">
                </div>
                <div class="form-group">
                    <label>URL:</label>
                    <input v-model="newService.url" type="text">
                </div>
                <div class="form-group">
                    <label>Timeout:</label>
                    <input v-model.number="newService.timeout" type="number" value="5">
                </div>
                <button @click="addService" class="btn btn-success">Add Service</button>
            </div>
            
            <!-- Test Section -->
            <div class="test-section">
                <h2>Test Gateway</h2>
                <div class="form-group">
                    <label>Order ID:</label>
                    <input v-model="testOrderId" type="text" placeholder="Enter order ID">
                </div>
                <button @click="testGateway" class="btn btn-primary">Test</button>
                
                <div v-if="testResult" style="margin-top: 20px;">
                    <h3>Result:</h3>
                    <pre>{{ JSON.stringify(testResult, null, 2) }}</pre>
                </div>
            </div>
        </div>

        <script>
            const { createApp } = Vue;
            
            createApp({
                data() {
                    return {
                        services: {},
                        newService: {
                            name: '',
                            url: '',
                            timeout: 5
                        },
                        testOrderId: '',
                        testResult: null
                    }
                },
                async mounted() {
                    await this.loadConfig();
                },
                methods: {
                    async loadConfig() {
                        try {
                            const response = await axios.get('/admin/config');
                            this.services = response.data;
                        } catch (error) {
                            alert('Error loading configuration');
                        }
                    },
                    async saveConfig() {
                        try {
                            await axios.put('/admin/config', this.services);
                            alert('Configuration saved successfully');
                        } catch (error) {
                            alert('Error saving configuration');
                        }
                    },
                    async addService() {
                        if (!this.newService.name || !this.newService.url) {
                            alert('Please fill in all fields');
                            return;
                        }
                        
                        try {
                            await axios.post(`/admin/config/${this.newService.name}`, {
                                url: this.newService.url,
                                timeout: this.newService.timeout,
                                enabled: true,
                                headers: {}
                            });
                            
                            this.newService = { name: '', url: '', timeout: 5 };
                            await this.loadConfig();
                            alert('Service added successfully');
                        } catch (error) {
                            alert('Error adding service');
                        }
                    },
                    async removeService(serviceName) {
                        if (confirm(`Are you sure you want to remove ${serviceName}?`)) {
                            try {
                                await axios.delete(`/admin/config/${serviceName}`);
                                await this.loadConfig();
                                alert('Service removed successfully');
                            } catch (error) {
                                alert('Error removing service');
                            }
                        }
                    },
                    async testGateway() {
                        if (!this.testOrderId) {
                            alert('Please enter an order ID');
                            return;
                        }
                        
                        try {
                            const response = await axios.post('/api/order', {
                                order_id: this.testOrderId
                            });
                            this.testResult = response.data;
                        } catch (error) {
                            this.testResult = { error: error.message };
                        }
                    }
                }
            }).mount('#app');
        </script>
    </body>
    </html>
    """

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)