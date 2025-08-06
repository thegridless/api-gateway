# Задача
```
помоги решить мне задачу. мне необходимо разработать системы (api gateway) для сторонних сервисов извне для получения запросов из внутрении сервисов. обозначим эту систему как Client1. 
задача должна решаться следующая: 
Client отправляет запрос с oreder_id, на api gateway - и получает ответ либо от Service1, либо ( доработка ) Service1 + Service2 . ( merged response) 

Предложи варианты решения это задачи - напрмиер готовые и доступные open-source ресурсы без оплаты типа Apisix (traefik платный и kong тоже) либо же какие ещё вариант с разработкой собственного высоконагруженного сервиса и подход для формирования динамических конфигураций
```
Рассмотрю несколько вариантов решения вашей задачи API Gateway с возможностью объединения ответов от нескольких сервисов:

## 1. Open-Source API Gateway решения

### Apache APISIX (Рекомендуемый)
```yaml
# File: /home/leonov-k/Documents/Projects/kong/apisix-docker-compose.yml
version: '3.8'

services:
  apisix-dashboard:
    image: apache/apisix-dashboard:3.0.1-alpine
    restart: always
    volumes:
      - ./dashboard_conf/conf.yaml:/usr/local/apisix-dashboard/conf/conf.yaml
    ports:
      - "9000:9000"
    networks:
      - apisix

  apisix:
    image: apache/apisix:3.7.0-debian
    restart: always
    volumes:
      - ./apisix_conf/config.yaml:/usr/local/apisix/conf/config.yaml:ro
    depends_on:
      - etcd
    ports:
      - "9080:9080/tcp"
      - "9091:9091/tcp"
      - "9443:9443/tcp"
      - "9092:9092/tcp"
    networks:
      - apisix

  etcd:
    image: bitnami/etcd:3.4.15
    restart: always
    volumes:
      - etcd_data:/bitnami/etcd
    environment:
      ETCD_ENABLE_V2: "true"
      ALLOW_NONE_AUTHENTICATION: "yes"
      ETCD_ADVERTISE_CLIENT_URLS: "http://etcd:2379"
      ETCD_LISTEN_CLIENT_URLS: "http://0.0.0.0:2379"
    ports:
      - "2379:2379/tcp"
    networks:
      - apisix

  # Ваши микросервисы
  service1:
    image: your-service1:latest
    ports:
      - "8081:8080"
    networks:
      - apisix

  service2:
    image: your-service2:latest
    ports:
      - "8082:8080"
    networks:
      - apisix

volumes:
  etcd_data:

networks:
  apisix:
    driver: bridge
```

### Envoy Proxy
```yaml
# File: /home/leonov-k/Documents/Projects/kong/envoy-docker-compose.yml
version: '3.8'

services:
  envoy:
    image: envoyproxy/envoy:v1.28-latest
    ports:
      - "8080:8080"
      - "9901:9901"
    volumes:
      - ./envoy.yaml:/etc/envoy/envoy.yaml
    networks:
      - envoy-net

  service1:
    image: your-service1:latest
    ports:
      - "8081:8080"
    networks:
      - envoy-net

  service2:
    image: your-service2:latest
    ports:
      - "8082:8080"
    networks:
      - envoy-net

networks:
  envoy-net:
    driver: bridge
```

## 2. Собственное решение на Go

### Основной API Gateway сервис
```go
// File: /home/leonov-k/Documents/Projects/kong/gateway/main.go
package main

import (
    "context"
    "encoding/json"
    "fmt"
    "log"
    "net/http"
    "sync"
    "time"

    "github.com/gorilla/mux"
)

type Gateway struct {
    services map[string]ServiceConfig
    mu       sync.RWMutex
}

type ServiceConfig struct {
    URL     string `json:"url"`
    Timeout int    `json:"timeout"`
    Enabled bool   `json:"enabled"`
}

type OrderRequest struct {
    OrderID string `json:"order_id"`
}

type ServiceResponse struct {
    Service string      `json:"service"`
    Data    interface{} `json:"data"`
    Error   string      `json:"error,omitempty"`
}

type MergedResponse struct {
    OrderID   string            `json:"order_id"`
    Services  []ServiceResponse `json:"services"`
    Timestamp time.Time         `json:"timestamp"`
}

func NewGateway() *Gateway {
    return &Gateway{
        services: map[string]ServiceConfig{
            "service1": {
                URL:     "http://service1:8080",
                Timeout: 5,
                Enabled: true,
            },
            "service2": {
                URL:     "http://service2:8080",
                Timeout: 5,
                Enabled: true,
            },
        },
    }
}

func (g *Gateway) handleOrder(w http.ResponseWriter, r *http.Request) {
    var req OrderRequest
    if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
        http.Error(w, "Invalid request", http.StatusBadRequest)
        return
    }

    // Определяем какие сервисы нужно вызвать на основе бизнес-логики
    servicesToCall := g.determineServices(req.OrderID)
    
    // Параллельно вызываем сервисы
    responses := g.callServicesParallel(req.OrderID, servicesToCall)
    
    result := MergedResponse{
        OrderID:   req.OrderID,
        Services:  responses,
        Timestamp: time.Now(),
    }

    w.Header().Set("Content-Type", "application/json")
    json.NewEncoder(w).Encode(result)
}

func (g *Gateway) determineServices(orderID string) []string {
    // Бизнес-логика для определения каких сервисов вызывать
    // Например, на основе типа заказа, региона и т.д.
    
    g.mu.RLock()
    defer g.mu.RUnlock()
    
    var services []string
    for name, config := range g.services {
        if config.Enabled {
            services = append(services, name)
        }
    }
    return services
}

func (g *Gateway) callServicesParallel(orderID string, services []string) []ServiceResponse {
    var wg sync.WaitGroup
    responses := make([]ServiceResponse, len(services))
    
    for i, serviceName := range services {
        wg.Add(1)
        go func(index int, name string) {
            defer wg.Done()
            responses[index] = g.callService(orderID, name)
        }(i, serviceName)
    }
    
    wg.Wait()
    return responses
}

func (g *Gateway) callService(orderID, serviceName string) ServiceResponse {
    g.mu.RLock()
    config, exists := g.services[serviceName]
    g.mu.RUnlock()
    
    if !exists {
        return ServiceResponse{
            Service: serviceName,
            Error:   "Service not configured",
        }
    }

    ctx, cancel := context.WithTimeout(context.Background(), 
        time.Duration(config.Timeout)*time.Second)
    defer cancel()

    url := fmt.Sprintf("%s/order/%s", config.URL, orderID)
    req, err := http.NewRequestWithContext(ctx, "GET", url, nil)
    if err != nil {
        return ServiceResponse{
            Service: serviceName,
            Error:   err.Error(),
        }
    }

    client := &http.Client{}
    resp, err := client.Do(req)
    if err != nil {
        return ServiceResponse{
            Service: serviceName,
            Error:   err.Error(),
        }
    }
    defer resp.Body.Close()

    var data interface{}
    if err := json.NewDecoder(resp.Body).Decode(&data); err != nil {
        return ServiceResponse{
            Service: serviceName,
            Error:   err.Error(),
        }
    }

    return ServiceResponse{
        Service: serviceName,
        Data:    data,
    }
}

func (g *Gateway) updateConfig(w http.ResponseWriter, r *http.Request) {
    var newServices map[string]ServiceConfig
    if err := json.NewDecoder(r.Body).Decode(&newServices); err != nil {
        http.Error(w, "Invalid configuration", http.StatusBadRequest)
        return
    }

    g.mu.Lock()
    g.services = newServices
    g.mu.Unlock()

    w.WriteHeader(http.StatusOK)
    json.NewEncoder(w).Encode(map[string]string{"status": "updated"})
}

func main() {
    gateway := NewGateway()
    
    r := mux.NewRouter()
    r.HandleFunc("/api/order", gateway.handleOrder).Methods("POST")
    r.HandleFunc("/admin/config", gateway.updateConfig).Methods("PUT")
    
    log.Println("Gateway starting on :8080")
    log.Fatal(http.ListenAndServe(":8080", r))
}
```

### Dockerfile для Gateway
```dockerfile
# File: /home/leonov-k/Documents/Projects/kong/gateway/Dockerfile
FROM golang:1.21-alpine AS builder

WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download

COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o gateway .

FROM alpine:latest
RUN apk --no-cache add ca-certificates
WORKDIR /root/

COPY --from=builder /app/gateway .

EXPOSE 8080
CMD ["./gateway"]
```

### go.mod
```go
// File: /home/leonov-k/Documents/Projects/kong/gateway/go.mod
module gateway

go 1.21

require github.com/gorilla/mux v1.8.1
```

## 3. Решение на Node.js с Express

```javascript
// File: /home/leonov-k/Documents/Projects/kong/gateway-node/server.js
const express = require('express');
const axios = require('axios');
const app = express();

app.use(express.json());

// Конфигурация сервисов
let servicesConfig = {
    service1: {
        url: 'http://service1:8080',
        timeout: 5000,
        enabled: true
    },
    service2: {
        url: 'http://service2:8080',
        timeout: 5000,
        enabled: true
    }
};

// Основной endpoint для обработки заказов
app.post('/api/order', async (req, res) => {
    const { order_id } = req.body;
    
    if (!order_id) {
        return res.status(400).json({ error: 'order_id is required' });
    }

    try {
        const servicesToCall = determineServices(order_id);
        const responses = await callServicesParallel(order_id, servicesToCall);
        
        res.json({
            order_id,
            services: responses,
            timestamp: new Date().toISOString()
        });
    } catch (error) {
        res.status(500).json({ error: error.message });
    }
});

// Определение каких сервисов вызывать
function determineServices(orderId) {
    return Object.keys(servicesConfig).filter(
        name => servicesConfig[name].enabled
    );
}

// Параллельный вызов сервисов
async function callServicesParallel(orderId, services) {
    const promises = services.map(serviceName => 
        callService(orderId, serviceName)
    );
    
    return Promise.allSettled(promises).then(results =>
        results.map((result, index) => ({
            service: services[index],
            ...(result.status === 'fulfilled' 
                ? { data: result.value }
                : { error: result.reason.message })
        }))
    );
}

// Вызов отдельного сервиса
async function callService(orderId, serviceName) {
    const config = servicesConfig[serviceName];
    const url = `${config.url}/order/${orderId}`;
    
    const response = await axios.get(url, {
        timeout: config.timeout
    });
    
    return response.data;
}

// Endpoint для обновления конфигурации
app.put('/admin/config', (req, res) => {
    servicesConfig = req.body;
    res.json({ status: 'updated' });
});

const PORT = process.env.PORT || 8080;
app.listen(PORT, () => {
    console.log(`Gateway running on port ${PORT}`);
});
```

## 4. Обновленный docker-compose с собственным Gateway

```yaml
# File: /home/leonov-k/Documents/Projects/kong/gateway-compose.yml
version: '3.8'

services:
  # Ваш API Gateway
  api-gateway:
    build: ./gateway
    ports:
      - "8080:8080"
    environment:
      - SERVICE1_URL=http://service1:8080
      - SERVICE2_URL=http://service2:8080
    depends_on:
      - service1
      - service2
    networks:
      - gateway-net

  # Сервис 1
  service1:
    image: your-service1:latest
    ports:
      - "8081:8080"
    networks:
      - gateway-net

  # Сервис 2  
  service2:
    image: your-service2:latest
    ports:
      - "8082:8080"
    networks:
      - gateway-net

  # Redis для кеширования (опционально)
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    networks:
      - gateway-net

networks:
  gateway-net:
    driver: bridge
```

## Рекомендации по выбору:

1. **Apache APISIX** - лучший выбор для production, богатый функционал, активное сообщество
2. **Собственное решение на Go** - максимальная гибкость, высокая производительность
3. **Envoy Proxy** - если нужны продвинутые возможности service mesh
4. **Node.js решение** - быстрая разработка и прототипирование

Для вашей задачи рекомендую начать с **Apache APISIX** или собственного **Go решения**, в зависимости от требований к кастомизации.


## Промежуточные вопросы
```
1. apache apisix имеет достаточно кривой интерфейс, например, в версии 3.0.1 не открывается вкладка plugins, понизил до 3.0.0 тоже не работает + чтобы делать двойные запросы ( в две системы ), нужно знать lua script
2. не знаю go, можно заменить на sanic/fastapi ? + сделать ui для добавления кофнигурация? 
3. все ли беспланто? можно ли развернуть в docker? есть ли ui? 
4. тоже что и с пунктом 2
```


Отвечу по каждому пункту:

## 1. Apache APISIX - проблемы подтверждаются
Да, у APISIX действительно есть проблемы со стабильностью dashboard и сложность с Lua скриптами для объединения ответов.

## 2. Решение на FastAPI с UI

### Основной Gateway на FastAPI
```python
# File: /home/leonov-k/Documents/Projects/kong/gateway-fastapi/main.py
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
```

### requirements.txt
```txt
# File: /home/leonov-k/Documents/Projects/kong/gateway-fastapi/requirements.txt
fastapi==0.104.1
uvicorn[standard]==0.24.0
httpx==0.25.2
pydantic==2.5.0
```

### Dockerfile
```dockerfile
# File: /home/leonov-k/Documents/Projects/kong/gateway-fastapi/Dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
```

## 3. Envoy Proxy - бесплатный, но сложный

**Плюсы:**
- Полностью бесплатный
- Высокая производительность
- Можно развернуть в Docker
- Есть Envoy Admin UI (базовый)

**Минусы:**
- Сложная конфигурация
- Нет удобного UI для управления
- Требует знания YAML конфигураций

```yaml
# File: /home/leonov-k/Documents/Projects/kong/envoy/envoy.yaml
static_resources:
  listeners:
  - name: listener_0
    address:
      socket_address:
        address: 0.0.0.0
        port_value: 8080
    filter_chains:
    - filters:
      - name: envoy.filters.network.http_connection_manager
        typed_config:
          "@type": type.googleapis.com/envoy.extensions.filters.network.http_connection_manager.v3.HttpConnectionManager
          stat_prefix: ingress_http
          route_config:
            name: local_route
            virtual_hosts:
            - name: local_service
              domains: ["*"]
              routes:
              - match:
                  prefix: "/api/order"
                route:
                  cluster: gateway_service
          http_filters:
          - name: envoy.filters.http.router

  clusters:


