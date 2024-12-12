## 📝 Introduction
The **Guggiana Project** is an advanced AWS-based serverless application designed to handle content-to-speech workflows. It integrates various AWS services such as Step Functions, Polly, S3, and DynamoDB to process, translate, and convert text content into audio in multiple languages. The application is built using **TypeScript** and leverages the **AWS CDK (Cloud Development Kit)** for infrastructure as code.

This project is particularly useful for applications requiring multilingual text-to-speech capabilities, such as news platforms, accessibility tools, or content distribution systems.

---

## 🌟 Features
The repository includes the following features:
- **Content-to-Speech Workflow**: Converts articles into audio using AWS Polly.
- **Multilingual Support**: Processes content in multiple languages, including English, Spanish, French, German, and Portuguese.
- **Dynamic Language Detection**: Automatically translates content before generating audio.
- **SSML Support**: Prepares text in SSML (Speech Synthesis Markup Language) for enhanced audio quality.
- **AWS Step Functions**: Orchestrates workflows for tasks such as translation, speech synthesis, and merging audio.
- **DynamoDB Integration**: Stores metadata and processing statuses for content.
- **S3 Storage**: Manages audio files in S3 for easy accessibility.
- **Error Handling and Retry Mechanism**: Ensures reliable execution of workflows.

---

## 📋 Requirements
Before using this repository, ensure you have the following:
- **Node.js** (>= 14.x)
- **AWS CDK** (>= 2.x)
- **AWS Account** with permissions to use:
  - S3
  - DynamoDB
  - Polly
  - Step Functions
  - Lambda
- **AWS CLI**, configured with appropriate credentials.
- **TypeScript** (>= 4.x)

---

## ⚙️ Installation
Follow these steps to set up the project:
1. Clone the repository:
   ```bash
   git clone https://github.com/gaulatti/guggiana.git
   cd guggiana
   ```
2. Install dependencies:
   ```bash
   npm install
   ```
3. Bootstrap AWS CDK:
   ```bash
   cdk bootstrap
   ```

---

## 🚀 Usage
### Deploying the Stack
To deploy the infrastructure:
```bash
cdk deploy
```

### Running Locally
You can test individual Lambda functions locally using AWS SAM CLI:
```bash
sam local invoke <FunctionName> --event event.json
```

### Testing
Run unit tests to ensure the application is working as expected:
```bash
npm test
```

---

## 🔧 Configuration
The application uses environment variables for configuration. These include:
- `TABLE_NAME`: DynamoDB table name.
- `BUCKET_NAME`: S3 bucket for storing audio files.
- `STATE_MACHINE_ARN`: ARN of the Step Functions state machine.

Set these variables in your environment or an `.env` file:
```bash
TABLE_NAME="your_table_name"
BUCKET_NAME="your_bucket_name"
STATE_MACHINE_ARN="your_state_machine_arn"
```

---

## 🤝 Contributing
Contributions are welcome! To contribute:
1. Fork the repository.
2. Create a new branch:
   ```bash
   git checkout -b feature/your-feature
   ```
3. Commit your changes:
   ```bash
   git commit -m "Add your feature"
   ```
4. Push to your branch:
   ```bash
   git push origin feature/your-feature
   ```
5. Open a Pull Request.

---

## 📜 License
This project is licensed under the **MIT License**. See the LICENSE file for details.

```markdown
MIT License

Copyright (c) 2023

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
```

---

## 🛠️ Framework and Language
This project is developed using:
- **Language**: TypeScript
- **Framework**: AWS CDK
- **Cloud Provider**: AWS

Enjoy using **Guggiana**! 🚀
