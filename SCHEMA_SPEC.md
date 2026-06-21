# PlanToPlate - Schema Specification

## Java Environment
- **Java Version:** 21 (LTS)
- **Build Tool:** Maven 3.x

## Build Profile Properties
```xml
<properties>
    <java.version>21</java.version>
    <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
    <project.reporting.outputEncoding>UTF-8</project.reporting.outputEncoding>
</properties>
```

## Maven Dependencies (Core Stack)
| Dependency | Version/Scope | Purpose |
|------------|---------------|---------|
| `spring-boot-starter-web` | 3.4.1 (parent BOM) | REST API, servlet container, JSON |
| `spring-boot-starter-data-jpa` | 3.4.1 (parent BOM) | JPA persistence abstraction |
| `spring-boot-starter-thymeleaf` | 3.4.1 (parent BOM) | Server-side template engine |
| `spring-boot-starter-validation` | 3.4.1 (parent BOM) | Jakarta Bean Validation |
| `lombok` | optional | Annotation-based boilerplate reduction |
| `sqlite-jdbc` | 3.46.0.0 | SQLite JDBC driver |
| `hibernate-community-dialects` | 6.6.2.Final | SQLite dialect for Hibernate |
| `spring-boot-starter-test` | test scope | Testing framework |

## SQLite Database Configuration
- **Driver:** `org.sqlite.JDBC`
- **Connection URL:** `jdbc:sqlite:plantoplate.db?journal_mode=WAL&busy_timeout=5000`
- **Journal Mode:** WAL (Write-Ahead Logging) - enables multi-threaded access without thread-lock exceptions
- **Busy Timeout:** 5000ms (5 seconds)

### SQLite Dialect
```java
org.hibernate.community.dialect.SQLiteDialect
```

## Hibernate Configuration
- **ddl-auto:** `update` (automated schema tracking)
- **show-sql:** `true` (SQL logging for debugging)
- **Virtual Threads:** Project Loom enabled (`spring.threads.virtual.enabled=true`)

## Application Startup Behavior
1. Virtual threads enabled for high-concurrency hypermedia rendering
2. SQLite connection pool provisions each active connection with:
   - `PRAGMA journal_mode=WAL;`
   - `PRAGMA busy_timeout=5000;`
3. Hibernate tracks entity schema changes to embedded `plantoplate.db` file

## Logging Configuration
```yaml
logging:
  level:
    org.hibernate.SQL: debug
    org.hibernate.type.descriptor.sql.BasicBinder: trace
```

## Maven Build Artifacts
- **JAR:** `target/plantoplate-1.0.0-SNAPSHOT.jar`
- **Test Results:** 4 tests (1 integration + 3 webMvc) - all PASSING

---
*Last updated: Task 1 - Project Skeleton & SQLite WAL Provisioning [COMPLETE]*
